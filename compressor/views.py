import os

from django.db import transaction
from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import get_object_or_404, render
from django.utils.encoding import escape_uri_path
from django.utils.html import format_html

from .models import (
    CompressionPreset,
    CompatibilityLevel,
    JobInput,
    JobMode,
    JobStatus,
    PDFJob,
)
from .tasks import compress_pdf, extract_images, merge_pdfs

MAX_UPLOAD_SIZE = 100 * 1024 * 1024  # 100 MB per file
MERGE_MIN_FILES = 2
MERGE_MAX_FILES = 100  # invoices with up to ~90 delivery notes
MERGE_MAX_TOTAL_SIZE = 300 * 1024 * 1024  # 300 MB per merge job


def index(request):
    jobs = PDFJob.objects.all()[:20]
    presets = CompressionPreset.choices

    return render(
        request,
        "compressor/index.html",
        {
            "jobs": jobs,
            "presets": presets,
            "compatibilities": CompatibilityLevel.choices,
            "modes": JobMode.choices,
        },
    )


def upload(request):
    if request.method != "POST":
        return HttpResponse("Método no permitido", status=405)

    if request.POST.get("mode") == JobMode.MERGE:
        return _upload_merge(request)

    pdf_file = request.FILES.get("pdf_file")
    preset = request.POST.get("preset", "ebook")

    if not pdf_file:
        return HttpResponse(
            '<div class="alert alert-danger">Debes seleccionar un archivo PDF.</div>',
            status=400,
        )

    if not pdf_file.name.lower().endswith(".pdf"):
        return HttpResponse(
            '<div class="alert alert-danger">Solo se permiten archivos PDF.</div>',
            status=400,
        )

    if pdf_file.size > MAX_UPLOAD_SIZE:
        return HttpResponse(
            '<div class="alert alert-danger">El archivo excede el límite de 100 MB.</div>',
            status=400,
        )

    if preset not in CompressionPreset.values:
        preset = "ebook"

    compatibility = request.POST.get("compatibility", "pdf-1.7")
    if compatibility not in CompatibilityLevel.values:
        compatibility = "pdf-1.7"

    mode = request.POST.get("mode", JobMode.COMPRESS)
    if mode not in JobMode.values:
        mode = JobMode.COMPRESS

    job = PDFJob.objects.create(
        original_file=pdf_file,
        original_filename=pdf_file.name,
        original_size=pdf_file.size,
        preset=preset,
        compatibility=compatibility,
        mode=mode,
    )

    if mode == JobMode.EXTRACT_IMAGES:
        task = extract_images.delay(str(job.id))
    else:
        task = compress_pdf.delay(str(job.id))

    job.celery_task_id = task.id
    job.save(update_fields=["celery_task_id"])

    return render(request, "compressor/_job_card.html", {"job": job})


def _error(message):
    """400 alert; `message` is plain text and gets escaped (it may carry filenames)."""
    return HttpResponse(
        format_html('<div class="alert alert-danger">{}</div>', message), status=400
    )


def _upload_merge(request):
    pdf_files = request.FILES.getlist("pdf_files")

    if len(pdf_files) < MERGE_MIN_FILES:
        return _error("Selecciona al menos 2 archivos PDF para combinar.")
    if len(pdf_files) > MERGE_MAX_FILES:
        return _error("Máximo 100 archivos por combinación.")
    for pdf_file in pdf_files:
        if not pdf_file.name.lower().endswith(".pdf"):
            return _error(f"Solo se permiten archivos PDF: {pdf_file.name}.")
        if pdf_file.size > MAX_UPLOAD_SIZE:
            return _error(f"{pdf_file.name} excede el límite de 100 MB.")
    total_size = sum(pdf_file.size for pdf_file in pdf_files)
    if total_size > MERGE_MAX_TOTAL_SIZE:
        return _error("El total excede el límite de 300 MB.")

    preset = request.POST.get("preset", "ebook")
    if preset not in CompressionPreset.values:
        preset = "ebook"
    compatibility = request.POST.get("compatibility", "pdf-1.7")
    if compatibility not in CompatibilityLevel.values:
        compatibility = "pdf-1.7"

    with transaction.atomic():
        job = PDFJob.objects.create(
            original_filename=pdf_files[0].name,
            original_size=total_size,
            preset=preset,
            compatibility=compatibility,
            mode=JobMode.MERGE,
        )
        for position, pdf_file in enumerate(pdf_files):
            JobInput.objects.create(
                job=job,
                file=pdf_file,
                original_filename=pdf_file.name,
                size=pdf_file.size,
                position=position,
            )

        def enqueue():
            task = merge_pdfs.delay(str(job.id))
            PDFJob.objects.filter(id=job.id).update(celery_task_id=task.id)

        # Enqueue only once the inputs are committed, or the worker may not see them.
        transaction.on_commit(enqueue)

    return render(request, "compressor/_job_card.html", {"job": job})


def job_status(request, job_id):
    job = get_object_or_404(PDFJob, id=job_id)
    response = render(request, "compressor/_job_card.html", {"job": job})
    if job.status in (JobStatus.COMPLETED, JobStatus.FAILED):
        response["HX-Trigger"] = "jobFinished"
    return response


def download(request, job_id):
    job = get_object_or_404(PDFJob, id=job_id, status=JobStatus.COMPLETED)

    if not job.compressed_file or not os.path.exists(job.compressed_file.path):
        raise Http404("El archivo comprimido no existe.")

    with open(job.compressed_file.path, "rb") as f:
        content = f.read()

    if job.mode == JobMode.EXTRACT_IMAGES:
        base = os.path.splitext(job.original_filename)[0]
        filename = f"{base}_imagenes.zip"
        content_type = "application/zip"
    else:
        filename = job.original_filename
        content_type = "application/pdf"

    job.delete_with_files()

    response = HttpResponse(content, content_type=content_type)
    response["Content-Disposition"] = (
        f"attachment; filename*=UTF-8''{escape_uri_path(filename)}"
    )
    response["Content-Length"] = str(len(content))
    return response
