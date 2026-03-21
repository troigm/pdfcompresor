from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from compressor.models import PDFJob


class Command(BaseCommand):
    help = "Elimina jobs y archivos anteriores a COMPRESSED_FILE_TTL_HOURS"

    def handle(self, *args, **options):
        ttl_hours = getattr(settings, "COMPRESSED_FILE_TTL_HOURS", 24)
        cutoff = timezone.now() - timedelta(hours=ttl_hours)
        old_jobs = PDFJob.objects.filter(created_at__lt=cutoff)

        count = 0
        for job in old_jobs:
            if job.original_file:
                job.original_file.delete(save=False)
            if job.compressed_file:
                job.compressed_file.delete(save=False)
            job.delete()
            count += 1

        self.stdout.write(self.style.SUCCESS(f"Eliminados {count} jobs antiguos."))
