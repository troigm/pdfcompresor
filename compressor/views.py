import os

from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import get_object_or_404, render
from django.utils.encoding import escape_uri_path

from .models import CompressionPreset, CompatibilityLevel, JobMode, JobStatus, PDFJob
from .tasks import compress_pdf, extract_images

MAX_UPLOAD_SIZE = 100 * 1024 * 1024  # 100 MB


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

    original_path = job.original_file.path if job.original_file else None
    compressed_path = job.compressed_file.path

    for path in (original_path, compressed_path):
        if path and os.path.exists(path):
            try:
                os.remove(path)
            except OSError:
                pass
    job.delete()

    response = HttpResponse(content, content_type=content_type)
    response["Content-Disposition"] = (
        f"attachment; filename*=UTF-8''{escape_uri_path(filename)}"
    )
    response["Content-Length"] = str(len(content))
    return response
