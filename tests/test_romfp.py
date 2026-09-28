"""romfp's fast paths for small integers agree with the ROM's own calculator.

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

HAVE = hbcimage.DEFAULT_TAPE.exists() and hbcimage.DEFAULT_ROM.exists()


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


if __name__ == '__main__':
    unittest.main()
