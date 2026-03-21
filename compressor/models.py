import uuid

from django.db import models


class CompatibilityLevel(models.TextChoices):
    PDF_1_4 = "pdf-1.4", "Máxima compatibilidad (PDF 1.4)"
    PDF_1_5 = "pdf-1.5", "Mejor compresión (PDF 1.5)"
    PDF_1_7 = "pdf-1.7", "Moderno (PDF 1.7)"
    PDFA_2B = "pdfa-2b", "Archivado (PDF/A-2b)"


class CompressionPreset(models.TextChoices):
    SCREEN = "screen", "Pantalla (72 dpi) — mínimo tamaño"
    EBOOK = "ebook", "eBook (150 dpi) — equilibrado"
    PRINTER = "printer", "Impresora (300 dpi) — alta calidad"
    PREPRESS = "prepress", "Preimpresión (300 dpi) — máxima calidad"


class JobStatus(models.TextChoices):
    PENDING = "pending", "Pendiente"
    PROCESSING = "processing", "Procesando"
    COMPLETED = "completed", "Completado"
    FAILED = "failed", "Fallido"


class PDFJob(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    original_file = models.FileField(upload_to="uploads/%Y/%m/%d/")
    compressed_file = models.FileField(
        upload_to="compressed/%Y/%m/%d/", blank=True
    )
    original_filename = models.CharField(max_length=255)
    preset = models.CharField(max_length=20, choices=CompressionPreset.choices)
    compatibility = models.CharField(
        max_length=20,
        choices=CompatibilityLevel.choices,
        default=CompatibilityLevel.PDF_1_7,
    )
    status = models.CharField(
        max_length=20, choices=JobStatus.choices, default=JobStatus.PENDING
    )
    original_size = models.BigIntegerField(default=0)
    compressed_size = models.BigIntegerField(default=0)
    compression_ratio = models.FloatField(default=0)
    error_message = models.TextField(blank=True)
    celery_task_id = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.original_filename} ({self.status})"

    @property
    def savings_percent(self):
        if self.original_size and self.compressed_size:
            return (1 - self.compressed_size / self.original_size) * 100
        return 0

    @property
    def original_size_human(self):
        return self._humanize_bytes(self.original_size)

    @property
    def compressed_size_human(self):
        return self._humanize_bytes(self.compressed_size)

    @staticmethod
    def _humanize_bytes(size):
        if size == 0:
            return "0 B"
        for unit in ("B", "KB", "MB", "GB"):
            if abs(size) < 1024:
                return f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} TB"
