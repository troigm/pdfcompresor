import os
import shutil
import tempfile

from django.core.files.base import ContentFile
from django.test import TestCase, override_settings

from compressor.models import JobInput, JobMode, PDFJob

TEST_MEDIA = tempfile.mkdtemp(prefix="test_media_")


@override_settings(MEDIA_ROOT=TEST_MEDIA)
class JobInputTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TEST_MEDIA, ignore_errors=True)

    def _merge_job(self):
        return PDFJob.objects.create(
            original_filename="fra.pdf", preset="ebook", mode=JobMode.MERGE
        )

    def _add_input(self, job, name, position):
        job_input = JobInput(job=job, original_filename=name, size=3, position=position)
        job_input.file.save(name, ContentFile(b"pdf"), save=False)
        job_input.save()
        return job_input

    def test_inputs_ordered_by_position(self):
        job = self._merge_job()
        for name, position in (("c.pdf", 2), ("a.pdf", 0), ("b.pdf", 1)):
            self._add_input(job, name, position)
        self.assertEqual([i.position for i in job.inputs.all()], [0, 1, 2])

    def test_delete_with_files_removes_every_file(self):
        job = self._merge_job()
        job.original_file.save("orig.pdf", ContentFile(b"o"), save=False)
        job.compressed_file.save("out.pdf", ContentFile(b"c"), save=False)
        job.save()
        inputs = [self._add_input(job, f"{n}.pdf", n) for n in range(2)]
        paths = [job.original_file.path, job.compressed_file.path] + [
            i.file.path for i in inputs
        ]
        self.assertTrue(all(os.path.exists(p) for p in paths))
        job_id = job.id

        job.delete_with_files()

        self.assertFalse(PDFJob.objects.filter(id=job_id).exists())
        self.assertEqual(JobInput.objects.count(), 0)
        self.assertTrue(all(not os.path.exists(p) for p in paths))

    def test_delete_with_files_tolerates_missing_files(self):
        job = self._merge_job()
        job_input = self._add_input(job, "gone.pdf", 0)
        os.remove(job_input.file.path)
        job.delete_with_files()
        self.assertFalse(PDFJob.objects.exists())
