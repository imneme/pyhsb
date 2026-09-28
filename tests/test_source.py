"""source.py: program lines stored the way the ROM stores them (hidden numbers,
BIN, DEF FN parameters, REMs and strings left alone), and directive lines.

    python3 -m unittest discover -s tests       (needs the ROM and the compiler tape; see README.md)
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import hbcimage   # noqa: E402
import rtlib      # noqa: E402
import romfp      # noqa: E402
import source     # noqa: E402
import tap        # noqa: E402

HAVE = hbcimage.DEFAULT_TAPE.exists() and hbcimage.DEFAULT_ROM.exists()
if HAVE:
    ROM = hbcimage.default_rom()
    KW = source.Keywords(ROM)
    FP = romfp.ROMFP(rtlib.Machine(hbcimage.default(), ROM))


def body(line):
    (n, b), = tap.split_lines(source.tokenize(line + '\n', KW, FP))
    return b


def small(n):
    return b'\x0e\x00\x00' + bytes([n & 0xFF, n >> 8]) + b'\x00'


@unittest.skipUnless(HAVE, 'needs the compiler tape and the ROM (see README.md)')
class TestTokenize(unittest.TestCase):
    def test_numbers(self):
        self.assertEqual(body('10 GO TO 100'), b'\xec100' + small(100) + b'\r')
        self.assertEqual(body('10 LET a1=2.5'), b'\xf1a1=2.5\x0e\x82\x20\x00\x00\x00\r')

    def test_bin(self):
        self.assertEqual(body('10 LET a=BIN 101'), b'\xf1a=\xc4101' + small(5) + b'\r')

    def test_strings_and_rem(self):
        self.assertEqual(body('10 PRINT "12";34'), b'\xf5"12";34' + small(34) + b'\r')
        self.assertEqual(body('10 REM 12 PRINT'), b'\xea12 PRINT\r')

    def test_def_fn(self):
        z = b'\x0e\x00\x00\x00\x00\x00'
        self.assertEqual(body('10 DEF FN f(x,y$)=x'), b'\xcef(x' + z + b',y$' + z + b')=x\r')

    def test_keywords_from_rom(self):
        self.assertEqual(KW.CODE_FOR['PRINT'], 0xF5)
        self.assertEqual(KW.CODE_FOR['PLAY'], 0xA4)
        self.assertEqual(KW.spell['GOTO'], 0xEC)


@unittest.skipUnless(HAVE, 'needs the compiler tape and the ROM (see README.md)')
class TestDirectives(unittest.TestCase):
    def test_add_and_find_open(self):
        prog = source.tokenize('10 PRINT 1\n', KW, FP)
        prog = source.add_directives(prog, ['INT a,b'], open_=True, kw=KW, fp=FP)
        lines = tap.split_lines(prog)
        self.assertEqual([n for n, _ in lines], [8, 9, 10])
        self.assertEqual(lines[0][1], b'\xea:\xbaa,b\r')              # REM : INT a,b, as tokens
        self.assertEqual(source.open_lines(prog), [9])

    def test_open_behind_colour_codes(self):
        prog = tap.join_lines([(10, b'\x12\x00\xea:\xd3\r')])       # {FLASH 0} REM : OPEN #
        self.assertEqual(source.open_lines(prog), [10])

    def test_tokenize_directives(self):
        prog = tap.join_lines([(5, b'\xea: INT a\r')])              # spelled out, as the 128 editor stores it
        (n, b), = tap.split_lines(source.tokenize_directives(prog, KW))
        self.assertEqual(b, b'\xea:\xbaa\r')


if __name__ == '__main__':
    unittest.main()
