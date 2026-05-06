import glob
import os
import shutil
import subprocess
import tempfile
import zipfile

from celery import shared_task
from django.conf import settings
from django.core.files import File
from django.utils import timezone


def _create_pdfa_def():
    """Create a temporary PDFA_def.ps file for PDF/A-2b conversion."""
    icc_path = None

    # Search for sRGB ICC profile in known locations
    gs_profiles = glob.glob("/usr/share/ghostscript/*/iccprofiles/default_rgb.icc")
    if gs_profiles:
        icc_path = gs_profiles[0]
    elif os.path.exists("/usr/share/color/icc/ghostscript/srgb.icc"):
        icc_path = "/usr/share/color/icc/ghostscript/srgb.icc"
    elif os.path.exists("/usr/share/color/icc/OpenICC/sRGB.icc"):
        icc_path = "/usr/share/color/icc/OpenICC/sRGB.icc"

    if icc_path is None:
        raise RuntimeError("No se encontró perfil ICC sRGB para PDF/A")

    content = (
        f"%!\n"
        f"[/_objdef {{icc_PDFA}} /type /stream /OBJ pdfmark\n"
        f"[{{icc_PDFA}} <</N 3>> /PUT pdfmark\n"
        f"[{{icc_PDFA}} ({icc_path}) (r) file /PUT pdfmark\n"
        f"[{{Catalog}} <</OutputIntents [<</Type /OutputIntent /S /GTS_PDFA1 "
        f"/DestOutputProfile {{icc_PDFA}} /OutputConditionIdentifier (sRGB) "
        f"/Info (sRGB IEC61966-2.1) "
        f"/RegistryName (http://www.color.org)>>]>> /PUT pdfmark\n"
    )

    tmp = tempfile.NamedTemporaryFile(suffix=".ps", delete=False, mode="w")
    tmp.write(content)
    tmp.close()
    return tmp.name


@shared_task(bind=True, max_retries=2, default_retry_delay=10)
def compress_pdf(self, job_id):
    from .models import JobStatus, PDFJob

    job = PDFJob.objects.get(id=job_id)
    job.status = JobStatus.PROCESSING
    job.save(update_fields=["status"])

    tmp_output = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
    tmp_output.close()
    pdfa_def_path = None

    try:
        gs_bin = getattr(settings, "GHOSTSCRIPT_BIN", "gs")
        input_path = job.original_file.path

        if job.compatibility == "pdfa-2b":
            pdfa_def_path = _create_pdfa_def()
            cmd = [
                gs_bin,
                "-dPDFA=2",
                "-dBATCH",
                "-dNOPAUSE",
                "-dNOOUTERSAVE",
                "-sDEVICE=pdfwrite",
                f"-dPDFSETTINGS=/{job.preset}",
                "-sColorConversionStrategy=RGB",
                "-dPDFACompatibilityPolicy=1",
                "-dEmbedAllFonts=true",
                "-dSubsetFonts=true",
                "-dColorImageDownsampleType=/Bicubic",
                "-dGrayImageDownsampleType=/Bicubic",
                "-dMonoImageDownsampleType=/Subsample",
                f"-sOutputFile={tmp_output.name}",
                pdfa_def_path,
                input_path,
            ]
        else:
            compat_map = {"pdf-1.4": "1.4", "pdf-1.5": "1.5", "pdf-1.7": "1.7"}
            compat_version = compat_map.get(job.compatibility, "1.4")
            cmd = [
                gs_bin,
                "-sDEVICE=pdfwrite",
                "-dNOPAUSE",
                "-dQUIET",
                "-dBATCH",
                "-dSAFER",
                f"-dCompatibilityLevel={compat_version}",
                f"-dPDFSETTINGS=/{job.preset}",
                "-dEmbedAllFonts=true",
                "-dSubsetFonts=true",
                "-dColorImageDownsampleType=/Bicubic",
                "-dGrayImageDownsampleType=/Bicubic",
                "-dMonoImageDownsampleType=/Subsample",
                f"-sOutputFile={tmp_output.name}",
                input_path,
            ]

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)

        if result.returncode != 0:
            raise RuntimeError(
                f"Ghostscript falló (code {result.returncode}): {result.stderr}"
            )

        compressed_size = os.path.getsize(tmp_output.name)
        original_size = os.path.getsize(input_path)

        # If compressed is larger, use the original
        if compressed_size >= original_size:
            shutil.copy2(input_path, tmp_output.name)
            compressed_size = original_size

        job.original_size = original_size
        job.compressed_size = compressed_size
        job.compression_ratio = compressed_size / original_size if original_size else 0

        with open(tmp_output.name, "rb") as f:
            job.compressed_file.save(
                f"compressed_{job.original_filename}", File(f), save=False
            )

        job.status = JobStatus.COMPLETED
        job.completed_at = timezone.now()
        job.save()

    except Exception as exc:
        if self.request.retries < self.max_retries:
            raise self.retry(exc=exc)

        job.status = JobStatus.FAILED
        job.error_message = str(exc)[:1000]
        job.save(update_fields=["status", "error_message"])

    finally:
        if os.path.exists(tmp_output.name):
            os.unlink(tmp_output.name)
        if pdfa_def_path and os.path.exists(pdfa_def_path):
            os.unlink(pdfa_def_path)


@shared_task(bind=True, max_retries=2, default_retry_delay=10)
def extract_images(self, job_id):
    from .models import JobStatus, PDFJob

    job = PDFJob.objects.get(id=job_id)
    job.status = JobStatus.PROCESSING
    job.save(update_fields=["status"])

    tmp_dir = tempfile.mkdtemp(prefix="pdfimg_")
    tmp_zip = tempfile.NamedTemporaryFile(suffix=".zip", delete=False)
    tmp_zip.close()

    try:
        input_path = job.original_file.path
        prefix = os.path.join(tmp_dir, "img")

        cmd = ["pdfimages", "-all", input_path, prefix]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)

        if result.returncode != 0:
            raise RuntimeError(
                f"pdfimages falló (code {result.returncode}): {result.stderr}"
            )

        images = sorted(
            p for p in glob.glob(os.path.join(tmp_dir, "img-*"))
            if os.path.isfile(p)
        )

        if not images:
            raise RuntimeError("El PDF no contiene imágenes embebidas extraíbles.")

        with zipfile.ZipFile(tmp_zip.name, "w", zipfile.ZIP_DEFLATED) as zf:
            for img_path in images:
                zf.write(img_path, arcname=os.path.basename(img_path))

        base = os.path.splitext(job.original_filename)[0]
        with open(tmp_zip.name, "rb") as f:
            job.compressed_file.save(f"{base}_imagenes.zip", File(f), save=False)

        job.original_size = os.path.getsize(input_path)
        job.compressed_size = os.path.getsize(tmp_zip.name)
        job.image_count = len(images)
        job.status = JobStatus.COMPLETED
        job.completed_at = timezone.now()
        job.save()

    except Exception as exc:
        if self.request.retries < self.max_retries:
            raise self.retry(exc=exc)

        job.status = JobStatus.FAILED
        job.error_message = str(exc)[:1000]
        job.save(update_fields=["status", "error_message"])

    finally:
        if os.path.exists(tmp_zip.name):
            os.unlink(tmp_zip.name)
        if os.path.exists(tmp_dir):
            shutil.rmtree(tmp_dir, ignore_errors=True)
