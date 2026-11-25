import shutil
import subprocess
import tempfile

from django.core.files.base import ContentFile
from django.test import TestCase, override_settings

from compressor.models import JobInput, JobMode, JobStatus, PDFJob
from compressor.tasks import merge_pdfs

TEST_MEDIA = tempfile.mkdtemp(prefix="test_media_")


def make_pdf(label, pages):
    """Real PDF with `label` printed on each of `pages` pages."""
    page_ps = f"/Helvetica findfont 24 scalefont setfont 72 720 moveto ({label}) show showpage "
    with tempfile.NamedTemporaryFile(suffix=".pdf") as out:
        subprocess.run(
            ["gs", "-q", "-sDEVICE=pdfwrite", "-o", out.name, "-c", page_ps * pages],
            check=True,
        )
        return open(out.name, "rb").read()


def pdfinfo_pages(path):
    output = subprocess.run(["pdfinfo", path], capture_output=True, text=True, check=True).stdout
    return int(next(l for l in output.splitlines() if l.startswith("Pages:")).split()[1])


def pdftotext_page(path, page):
    return subprocess.run(
        ["pdftotext", "-f", str(page), "-l", str(page), path, "-"],
        capture_output=True, text=True, check=True,
    ).stdout


@override_settings(MEDIA_ROOT=TEST_MEDIA)
class MergePdfsTaskTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TEST_MEDIA, ignore_errors=True)

    def _job_with_inputs(self, inputs):
        """inputs: list of (filename, bytes) in final order."""
        job = PDFJob.objects.create(
            original_filename=inputs[0][0],
            original_size=sum(len(c) for _, c in inputs),
            preset="ebook",
            compatibility="pdf-1.7",
            mode=JobMode.MERGE,
        )
        for position, (name, content) in enumerate(inputs):
            job_input = JobInput(job=job, original_filename=name, size=len(content), position=position)
            job_input.file.save(name, ContentFile(content), save=False)
            job_input.save()
        return job

    def test_merges_in_position_order(self):
        job = self._job_with_inputs([
            ("a.pdf", make_pdf("DOC-A", 1)),
            ("b.pdf", make_pdf("DOC-B", 2)),
            ("c.pdf", make_pdf("DOC-C", 1)),
        ])
        merge_pdfs.apply(args=[str(job.id)])
        job.refresh_from_db()

        self.assertEqual(job.status, JobStatus.COMPLETED, job.error_message)
        path = job.compressed_file.path
        self.assertEqual(pdfinfo_pages(path), 4)
        self.assertIn("DOC-A", pdftotext_page(path, 1))
        self.assertIn("DOC-B", pdftotext_page(path, 2))
        self.assertIn("DOC-B", pdftotext_page(path, 3))
        self.assertIn("DOC-C", pdftotext_page(path, 4))
        self.assertIsNotNone(job.completed_at)
        self.assertGreater(job.compressed_size, 0)

    def test_result_named_after_first_input_with_accents(self):
        job = self._job_with_inputs([
            ("Factura nº 12 (copia).pdf", make_pdf("FRA", 1)),
            ("Albarán 3.pdf", make_pdf("ALB", 1)),
        ])
        merge_pdfs.apply(args=[str(job.id)])
        job.refresh_from_db()

        self.assertEqual(job.status, JobStatus.COMPLETED, job.error_message)
        self.assertTrue(job.compressed_file.name.endswith(".pdf"))
        self.assertEqual(job.original_filename, "Factura nº 12 (copia).pdf")
        self.assertEqual(job.original_size, sum(i.size for i in job.inputs.all()))
        self.assertEqual(pdfinfo_pages(job.compressed_file.path), 2)

    def test_corrupt_input_marks_job_failed(self):
        job = self._job_with_inputs([
            ("a.pdf", make_pdf("DOC-A", 1)),
            ("roto.pdf", b"not a pdf"),
            ("c.pdf", make_pdf("DOC-C", 1)),
        ])
        merge_pdfs.apply(args=[str(job.id)])
        job.refresh_from_db()

        self.assertEqual(job.status, JobStatus.FAILED)
        self.assertTrue(job.error_message)
