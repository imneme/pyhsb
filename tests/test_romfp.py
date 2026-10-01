"""romfp's fast paths for small integers agree with the ROM's own calculator, and the
ROM's number reader is handed only the line it reads.

    python3 -m unittest discover -s tests       (needs the ROM and the compiler tape; see README.md)
"""
import random
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import hbcimage   # noqa: E402
import rtlib      # noqa: E402
import romfp      # noqa: E402
import compiler   # noqa: E402
import source     # noqa: E402

HAVE = hbcimage.DEFAULT_TAPE.exists() and hbcimage.DEFAULT_ROM.exists()
HAVE11 = hbcimage.TAPE_V11.exists() and hbcimage.ROM_V11.exists()


@unittest.skipUnless(HAVE, 'needs the compiler tape and the ROM (see README.md)')
class TestFastPaths(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fp = romfp.ROMFP(rtlib.Machine(hbcimage.default(), hbcimage.default_rom()))

    def values(self):
        rng = random.Random(1)
        return (list(range(-300, 300)) + [rng.randint(-65535, 65535) for _ in range(300)]
                + [-65535, 65535, 32767, 32768, -32768, -32769])

    def test_negate(self):
        for v in self.values():
            x = romfp.int_form(v)
            self.assertEqual(self.fp.calc([x], [romfp.C_NEGATE])[0], self.fp.negate(x), v)

    def test_round(self):
        ops = [romfp.C_DUPLICATE, romfp.C_LESS_0, romfp.C_JUMP_TRUE, 5, romfp.C_STK_HALF, romfp.C_ADDITION,
               romfp.C_JUMP, 3, romfp.C_STK_HALF, romfp.C_SUBTRACT]
        for v in self.values():
            x = romfp.int_form(v)
            rom = self.fp.truncate_to_hl(self.fp.calc([x], ops)[-1])
            self.assertEqual(rom, self.fp.round_to_hl(x), v)

    def test_rom_rounding_quirk(self):
        # the ROM's DEC_TO_FP makes 0.4999999998 of "0.5", and adding 0.5 rounds up to 1
        x, end = self.fp.dec_to_fp(b'0.5\r', 0)
        self.assertEqual(end, 3)
        self.assertEqual(self.fp.round_to_hl(x), 1)


@unittest.skipUnless(HAVE, 'needs the compiler tape and the ROM (see README.md)')
class TestDecToFp(unittest.TestCase):
    def test_only_the_line(self):
        # DEC_TO_FP is given its text in the interpreter's memory: the line up to its CR,
        # and nothing after it, which is the compiler's own working memory
        fp = romfp.ROMFP(rtlib.Machine(hbcimage.default(), hbcimage.default_rom()))
        text = bytearray(b'"1.5"\r') + bytearray(b'\xaa' * 2000)
        at = romfp.TEXT_AT
        fp.mem[at:at + 3000] = bytes([0x55]) * 3000
        x, end = fp.dec_to_fp(text, 1, at)
        self.assertEqual((x, end), (bytes([0x81, 0x40, 0, 0, 0]), 4))
        self.assertEqual(bytes(fp.mem[at + len(b'"1.5"\r'):at + 3000]), bytes([0x55]) * (3000 - 6))


@unittest.skipUnless(HAVE and HAVE11, 'needs both HiSoft BASIC tapes and both ROMs')
class V11(unittest.TestCase):
    def test_val_after_many_lines(self):
        # v1.1 reads lines in place; the ROM's DEC_TO_FP once got the rest of the program
        # copied over v1.1's line table, so a VAL "..." after 26 line-table entries broke
        # the jumps after it.  This program compiles to the same code in both versions.
        text = ('10 REM : OPEN #\n' + ''.join(f'{100 + 10 * i} IF a={i} THEN GO TO {110 + 10 * i}\n'
                                             for i in range(40))
                + '500 LET b=VAL "1.5": PRINT b\n510 GO TO 300\n')
        out = []
        for img, rom in ((hbcimage.default(), hbcimage.default_rom()), (hbcimage.v11(), hbcimage.v11_rom())):
            kw, fp = source.Keywords(rom), romfp.ROMFP(rtlib.Machine(img, rom))
            prog = source.tokenize(text, kw, fp)
            if img.v11:
                prog = source.tokenize_directives(prog, kw)
            out.append(compiler.Compiler(img, rom, exact=True).compile(prog))
        self.assertTrue(out[0].ok and out[1].ok)
        self.assertEqual(out[0].code, out[1].code)


if __name__ == '__main__':
    unittest.main()
