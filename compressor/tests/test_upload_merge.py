import shutil
import tempfile
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from compressor.models import JobMode, PDFJob

TEST_MEDIA = tempfile.mkdtemp(prefix="test_media_")


def pdf(name, content=b"%PDF-1.4 fake"):
    return SimpleUploadedFile(name, content, content_type="application/pdf")


@override_settings(MEDIA_ROOT=TEST_MEDIA)
@patch("compressor.views.merge_pdfs.delay")
class UploadMergeTests(TestCase):
    url = reverse("compressor:upload")

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TEST_MEDIA, ignore_errors=True)

    def _post(self, files, **extra):
        data = {"mode": "merge", "preset": "ebook", "compatibility": "pdf-1.7", "pdf_files": files}
        data.update(extra)
        with self.captureOnCommitCallbacks(execute=True):
            return self.client.post(self.url, data)

    def test_creates_job_with_inputs_in_upload_order(self, mock_delay):
        mock_delay.return_value.id = "task-1"
        resp = self._post([pdf("fra.pdf"), pdf("alb1.pdf"), pdf("alb2.pdf")])

        self.assertEqual(resp.status_code, 200)
        job = PDFJob.objects.get()
        self.assertEqual(job.mode, JobMode.MERGE)
        self.assertEqual(job.original_filename, "fra.pdf")
        self.assertEqual(job.original_size, 3 * len(b"%PDF-1.4 fake"))
        self.assertFalse(job.original_file)
        self.assertEqual(
            [i.original_filename for i in job.inputs.all()],
            ["fra.pdf", "alb1.pdf", "alb2.pdf"],
        )
        self.assertEqual([i.position for i in job.inputs.all()], [0, 1, 2])
        mock_delay.assert_called_once_with(str(job.id))
        self.assertEqual(job.celery_task_id, "task-1")

    def test_same_file_twice_is_kept_twice(self, mock_delay):
        mock_delay.return_value.id = "t"
        self._post([pdf("a.pdf"), pdf("a.pdf")])
        self.assertEqual(PDFJob.objects.get().inputs.count(), 2)

    def test_rejects_single_file(self, mock_delay):
        resp = self._post([pdf("a.pdf")])
        self.assertEqual(resp.status_code, 400)
        self.assertIn("al menos 2", resp.content.decode())
        self.assertFalse(PDFJob.objects.exists())
        mock_delay.assert_not_called()

    def test_accepts_100_files(self, mock_delay):
        mock_delay.return_value.id = "t"
        resp = self._post([pdf(f"alb{n}.pdf") for n in range(100)])
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(PDFJob.objects.get().inputs.count(), 100)

    def test_rejects_101_files(self, mock_delay):
        resp = self._post([pdf(f"alb{n}.pdf") for n in range(101)])
        self.assertEqual(resp.status_code, 400)
        self.assertIn("Máximo 100", resp.content.decode())
        self.assertFalse(PDFJob.objects.exists())

    def test_rejects_non_pdf(self, mock_delay):
        resp = self._post([pdf("a.pdf"), SimpleUploadedFile("b.txt", b"x")])
        self.assertEqual(resp.status_code, 400)
        self.assertIn("b.txt", resp.content.decode())
        self.assertFalse(PDFJob.objects.exists())

    def test_error_message_escapes_filename(self, mock_delay):
        resp = self._post([pdf("a.pdf"), SimpleUploadedFile("<b>x.txt", b"x")])
        self.assertEqual(resp.status_code, 400)
        self.assertNotIn("<b>x.txt", resp.content.decode())

    @patch("compressor.views.MAX_UPLOAD_SIZE", 5)
    def test_rejects_single_file_over_limit(self, mock_delay):
        resp = self._post([pdf("a.pdf", b"123"), pdf("grande.pdf", b"1234567")])
        self.assertEqual(resp.status_code, 400)
        self.assertIn("grande.pdf", resp.content.decode())
        self.assertFalse(PDFJob.objects.exists())

    @patch("compressor.views.MERGE_MAX_TOTAL_SIZE", 10)
    def test_rejects_total_over_limit(self, mock_delay):
        resp = self._post([pdf("a.pdf"), pdf("b.pdf")])
        self.assertEqual(resp.status_code, 400)
        self.assertIn("300 MB", resp.content.decode())
        self.assertFalse(PDFJob.objects.exists())

    @patch("compressor.views.compress_pdf.delay")
    def test_compress_mode_unchanged(self, mock_compress, mock_delay):
        mock_compress.return_value.id = "c"
        resp = self.client.post(self.url, {"mode": "compress", "preset": "ebook", "pdf_file": pdf("x.pdf")})
        self.assertEqual(resp.status_code, 200)
        job = PDFJob.objects.get()
        self.assertEqual(job.mode, JobMode.COMPRESS)
        self.assertEqual(job.inputs.count(), 0)
        mock_compress.assert_called_once()
        mock_delay.assert_not_called()
