"""pyhsb.py on a program without REM : OPEN #: no code, as the original, but it says why.

    python3 -m unittest discover -s tests       (needs the ROM and the compiler tape; see README.md)
"""
import contextlib
import io
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import hbcimage   # noqa: E402
import pyhsb      # noqa: E402

HAVE = hbcimage.DEFAULT_TAPE.exists() and hbcimage.DEFAULT_ROM.exists()
PROGRAM = '10 FOR i=1 TO 3\n20 PRINT i\n30 NEXT i\n'


@unittest.skipUnless(HAVE, 'needs the compiler tape and the ROM (see README.md)')
class TestOpen(unittest.TestCase):
    def compile(self, *flags):
        with tempfile.TemporaryDirectory() as d:
            src = Path(d) / 'tiny.bas'
            src.write_text(PROGRAM)
            out, err = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                status = pyhsb.main([str(src), '-o', str(Path(d) / 'tiny.tap'), *flags])
            return status, out.getvalue(), err.getvalue()

    def test_without_open_says_why_there_is_no_code(self):
        status, out, err = self.compile()
        self.assertEqual(status, 0)
        self.assertIn('-> 0 bytes of code', out)
        self.assertIn('no REM : OPEN #', err)
        self.assertIn('--open', err)

    def test_with_open_compiles_and_says_nothing_extra(self):
        status, out, err = self.compile('--open')
        self.assertEqual(status, 0)
        self.assertNotIn('-> 0 bytes of code', out)
        self.assertNotIn('no REM : OPEN #', err)


if __name__ == '__main__':
    unittest.main()
