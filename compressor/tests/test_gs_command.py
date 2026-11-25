from django.test import SimpleTestCase

from compressor.tasks import build_gs_command


class BuildGsCommandTests(SimpleTestCase):
    def test_standard_command_keeps_flags_and_input_order(self):
        cmd = build_gs_command(["/a.pdf", "/b.pdf"], "/out.pdf", "ebook", "pdf-1.7", None)
        self.assertEqual(cmd[0], "gs")
        self.assertIn("-dCompatibilityLevel=1.7", cmd)
        self.assertIn("-dPDFSETTINGS=/ebook", cmd)
        self.assertIn("-dSAFER", cmd)
        self.assertIn("-sOutputFile=/out.pdf", cmd)
        self.assertEqual(cmd[-2:], ["/a.pdf", "/b.pdf"])

    def test_pdfa_command_puts_def_before_inputs(self):
        cmd = build_gs_command(
            ["/a.pdf", "/b.pdf"], "/out.pdf", "printer", "pdfa-2b", "/def.ps"
        )
        self.assertIn("-dPDFA=2", cmd)
        self.assertIn("-dPDFSETTINGS=/printer", cmd)
        self.assertEqual(cmd[-3:], ["/def.ps", "/a.pdf", "/b.pdf"])

    def test_unknown_compatibility_falls_back_to_1_4(self):
        cmd = build_gs_command(["/a.pdf"], "/out.pdf", "ebook", "bogus", None)
        self.assertIn("-dCompatibilityLevel=1.4", cmd)

    def test_custom_gs_bin(self):
        cmd = build_gs_command(["/a.pdf"], "/out.pdf", "ebook", "pdf-1.7", None, gs_bin="/usr/bin/gs")
        self.assertEqual(cmd[0], "/usr/bin/gs")
