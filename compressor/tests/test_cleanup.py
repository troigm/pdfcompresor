import os
import shutil
import tempfile
from datetime import timedelta

from django.conf import settings
from django.core.files.base import ContentFile
from django.test import TestCase, override_settings
from django.utils import timezone

from compressor.models import JobInput, JobMode, PDFJob
from compressor.tasks import cleanup_old_jobs
from pdf_compressor.celery import app

TEST_MEDIA = tempfile.mkdtemp(prefix="test_media_")


@override_settings(MEDIA_ROOT=TEST_MEDIA, COMPRESSED_FILE_TTL_HOURS=24)
class CleanupOldJobsTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TEST_MEDIA, ignore_errors=True)

    def _merge_job(self, age_hours):
        job = PDFJob.objects.create(original_filename="fra.pdf", preset="ebook", mode=JobMode.MERGE)
        PDFJob.objects.filter(id=job.id).update(created_at=timezone.now() - timedelta(hours=age_hours))
        job_input = JobInput(job=job, original_filename="a.pdf", size=1, position=0)
        job_input.file.save("a.pdf", ContentFile(b"x"), save=False)
        job_input.save()
        return job, job_input.file.path

    def test_deletes_jobs_older_than_ttl_with_their_files(self):
        old_job, old_path = self._merge_job(age_hours=25)
        recent_job, recent_path = self._merge_job(age_hours=1)

        cleanup_old_jobs.apply()

        self.assertFalse(PDFJob.objects.filter(id=old_job.id).exists())
        self.assertFalse(os.path.exists(old_path))
        self.assertTrue(PDFJob.objects.filter(id=recent_job.id).exists())
        self.assertTrue(os.path.exists(recent_path))

    def test_beat_schedule_runs_registered_cleanup_task(self):
        entry = settings.CELERY_BEAT_SCHEDULE["cleanup-old-jobs"]
        self.assertEqual(entry["task"], "compressor.tasks.cleanup_old_jobs")
        self.assertIn(entry["task"], app.tasks)
