"""Big programs: the original's D and E commands (the two halves), its OKAY TO DELETE
BASIC? question, DO NOT TEST, and pyhsb's compile_whole, which joins the halves.

These check what can be checked without the original: the halves partition the whole
program, the placement arithmetic, and the answers.  Byte-for-byte agreement with the
original on the same programs was measured with the real compiler (see HACKING.md).

    python3 -m unittest discover -s tests       (needs the ROM and the compiler tape; see README.md)
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import compiler   # noqa: E402
import hbcimage   # noqa: E402
import romfp      # noqa: E402
import rtlib      # noqa: E402
import source     # noqa: E402

HAVE = hbcimage.DEFAULT_TAPE.exists() and hbcimage.DEFAULT_ROM.exists()
TOP = compiler.RAMTOP_X + 1

DENSE = 'LET a=b*c+d*e-f*g+h*i-j*k+l*m'      # REAL arithmetic: lots of code per byte of BASIC
WORDY = 'PRINT "' + 'z' * 60 + '"'


def lines(stmts):
    return ''.join(f'{10 + i} {s}\n' for i, s in enumerate(stmts))


def small_with_data():
    return lines(['REM : INT x,y', 'REM : OPEN #', 'FOR i=1 TO 3: READ x,y,q$: PRINT x;y;q$: NEXT i',
                  'DATA INT 1,2,"one"', 'DATA INT 3,4,"two"', 'DATA INT 5,6,"three"', 'PRINT "done"'])


def code_too_big(n=184, data=False, deffn=False):
    """code about 1.8 times its BASIC: it doesn't fit beside the program, but built over it,
    it never reaches a line before the line has been read"""
    s = ['REM : OPEN #']
    if deffn:
        s += ['DEF FN f(x)=x*x+1', 'PRINT FN f(3)']
    if data:
        s += ['READ q$: PRINT q$', 'DATA "' + 'y' * 200 + '"']
    return lines(s + [DENSE, WORDY] * n)


@unittest.skipUnless(HAVE, 'needs the HiSoft BASIC tape (v1.2) and the 128 ROM')
class BigPrograms(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        rom = hbcimage.default_rom()
        img = hbcimage.default()
        cls.c = compiler.Compiler(img, rom, exact=True)
        cls.fixed = compiler.Compiler(img, rom)
        cls.kw = source.Keywords(rom)
        cls.fp = romfp.ROMFP(rtlib.Machine(img, rom))

    def prog(self, text):
        return source.tokenize(text, self.kw, self.fp)

    def test_halves_partition_the_whole(self):
        p = self.prog(small_with_data())
        whole = self.c.compile(p)
        d = self.c.compile(p, 'D')
        e = self.c.compile(p, 'E')
        self.assertTrue(whole.ok and d.ok and e.ok)
        self.assertEqual(e.code + d.code, whole.code)
        self.assertEqual((e.load, d.load), (whole.load, whole.load + len(e.code)))
        self.assertEqual(d.mc_bytes, len(whole.code))
        # each half is built just below RAMTOP, so neither runs where it is: DO NOT TEST
        self.assertEqual((d.save + len(d.code), e.save + len(e.code)), (TOP, TOP))
        self.assertTrue(d.do_not_test and e.do_not_test and not whole.do_not_test)
        joined = compiler.join_parts(d, e)
        self.assertEqual((joined.code, joined.load), (whole.code, whole.load))

    def test_no_room_for_the_variables(self):
        # the code fits under RAMTOP but its variables don't: built without them, no question
        r = self.c.compile(self.prog(lines(['REM : OPEN #', 'DIM a(7800)', 'LET a(1)=5', 'PRINT a(1)']
                                           + ['REM ' + 'x' * 120] * 16)))
        self.assertTrue(r.ok)
        self.assertFalse(r.asked)
        self.assertTrue(r.do_not_test)
        self.assertEqual(r.save, TOP - len(r.code))
        self.assertEqual(r.load, TOP - len(r.code) - r.var_bytes)

    def test_delete_the_basic(self):
        p = self.prog(code_too_big())
        y = self.c.compile(p)
        self.assertTrue(y.ok and y.asked and y.deleted and y.do_not_test)
        self.assertEqual(y.save, TOP - len(y.code))
        n = self.c.compile(p, delete=False)
        self.assertFalse(n.ok)
        self.assertEqual(n.error_code, 108)
        self.assertTrue(n.asked)

    def test_use_d_e_and_compile_whole(self):
        p = self.prog(code_too_big(data=True))
        c = self.c.compile(p)
        self.assertEqual(c.error_code, 107)          # 'Use *D,*E'
        r = self.c.compile_whole(p)
        self.assertTrue(r.ok)
        self.assertEqual(r.mode, 'D+E')
        d, e = r.parts
        self.assertEqual(r.code, e.code + d.code)
        self.assertEqual(len(r.code), r.mc_bytes)
        self.assertEqual(r.load, TOP - r.mc_bytes - r.var_bytes)
        self.assertTrue(e.deleted and not d.deleted)
        self.assertEqual(self.c.compile_whole(p, delete=False).error_code, 108)

    def test_skipped_bytes_over_a_deleted_program(self):
        # DEF FN's parameter slot is skipped, not written: over a deleted program, the
        # original leaves the program's own bytes there (measured); fixed mode writes zeros
        p = self.prog(code_too_big(deffn=True))
        r = self.c.compile(p)
        (off, size), = r.unwritten
        self.assertEqual(r.code[off:off + size], p[off:off + size])
        f = self.fixed.compile(p)
        self.assertEqual(f.code[off:off + size], bytes(size))
        self.assertEqual(f.code[:off] + f.code[off + size:], r.code[:off] + r.code[off + size:])

    def test_too_big_even_without_the_basic(self):
        # the code and its variables must fit between 0x6000 and RAMTOP
        r = self.c.compile_whole(self.prog(lines(['REM : OPEN #'] + [DENSE] * 3000)))
        self.assertEqual(r.error_code, 108)
        self.assertFalse(r.asked)


if __name__ == '__main__':
    unittest.main()
