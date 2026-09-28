"""The user's own copy of the compiler, read at run time.

pyhsb carries none of HiSoft BASIC's bytes.  Everything that has to match
the original byte for byte (the runtime library, which the compiler emits
from its own emitter code) is taken from the user's tape, the way an
emulator asks for a ROM.

    img = Image.from_tape('HiSoft-BASIC-Compiler-v1.2-128K.tap')   # finds the 'hbc' CODE block
    img.version                                    # 'v1.2 (128)' when it is the known one
"""
import hashlib
from pathlib import Path

HBC_ORG = 48900          # 0xBF04: where the tape's hbc block loads (bank 1 from 0xC009 on)
HBC2_ORG = 23792         # 0x5CF0: side A's hbc2, the 48K compiler (v1.1), which runs where it loads

# sha256 of the hbc block's data, for naming versions.  (A hash, not the bytes.)
KNOWN = {
    '17271aa6656bb282ad5d16491ecd3e48c2f841219df9f1ac9dd0f3476047d14b': 'v1.2 (128)',
    'b3fb20debb186d74ca10d1ec7b09f1bc4cf12b89e092e4aca81741c3e00c5793': 'v1.1 (48K)',
}


class ImageError(Exception):
    pass


from tap import tap_blocks                           # noqa: E402


class Image:
    def __init__(self, data, org=HBC_ORG, source=''):
        self.data = bytes(data)
        self.org = org
        self.source = source
        self.sha256 = hashlib.sha256(self.data).hexdigest()
        self.version = KNOWN.get(self.sha256, 'unknown')
        self.extras = []

    def prior_ram(self, a):
        """What a freshly set-up machine holds at address a, as far as the tape can say:
        the compiler as loaded (v1.2's hbc at 48900 is still in RAM after being installed
        into the RAM disk) and the tape's other CODE blocks; zeros elsewhere."""
        for start, data in [(self.org, self.data)] + self.extras:
            if start <= a < start + len(data):
                return data[a - start]
        return 0

    @classmethod
    def from_tape(cls, path):
        path = Path(path).expanduser()
        blocks = tap_blocks(path.read_bytes())
        for i, b in enumerate(blocks[:-1]):
            if len(b) == 19 and b[0] == 0 and b[1] == 3:           # a CODE header
                name = b[2:12].decode('latin-1').rstrip()
                length = b[12] | b[13] << 8
                start = b[14] | b[15] << 8
                if (name.lower(), start) in (('hbc', HBC_ORG), ('hbc2', HBC2_ORG)):
                    data = blocks[i + 1][1:-1]
                    if len(data) != length:
                        raise ImageError(f'{path}: {name} block is {len(data)} bytes, header says {length}')
                    img = cls(data, start, str(path))
                    # the tape's other CODE blocks stay in RAM where they loaded (v1.1's hbc1 at
                    # 60000), and a fresh machine's untouched bytes are theirs
                    img.extras = [(b[14] | b[15] << 8, blocks[j + 1][1:-1]) for j, b in enumerate(blocks[:-1])
                                  if len(b) == 19 and b[0] == 0 and b[1] == 3 and j != i]
                    return img
        raise ImageError(f'{path}: no "hbc" CODE block at {HBC_ORG} (side B, the 128 version) '
                         f'or "hbc2" at {HBC2_ORG} (side A, the 48K version)')

    @property
    def v11(self):
        return self.org == HBC2_ORG

    @classmethod
    def from_bin(cls, path, org=HBC_ORG):
        path = Path(path).expanduser()
        return cls(path.read_bytes(), org, str(path))

    def byte(self, a):
        return self.data[a - self.org]

    def word(self, a):
        return self.data[a - self.org] | self.data[a - self.org + 1] << 8

    def load_into(self, mem):
        mem[self.org:self.org + len(self.data)] = self.data
        return mem


def _find(env, *names):
    """$env if it's set, else the first of these names found in the current directory
    or beside pyhsb itself (else the first name, for the error message)."""
    import os
    if os.environ.get(env):
        return Path(os.environ[env]).expanduser()
    for d in (Path.cwd(), Path(__file__).resolve().parent):
        for name in names:
            if (d / name).exists():
                return d / name
    return Path(names[0])


# the tapes as downloaded (see README.md), or as they're often called
DEFAULT_TAPE = _find('PYHSB_TAPE', 'HiSoft-BASIC-Compiler-v1.2-128K.tap', 'hsb-sb.tap')   # v1.2, the 128 compiler
DEFAULT_ROM = _find('PYHSB_ROM', '128-1.rom')          # the 128's ROM 1 (48 BASIC), paged while compiling
TAPE_V11 = _find('PYHSB_TAPE_V11', 'HiSoft-BASIC-Compiler-v1.1-48K.tap', 'hsb-sa.tap')  # v1.1, the 48K compiler
ROM_V11 = _find('PYHSB_ROM_V11', '48.rom')             # ... which runs on a 48K


def default_rom():
    return DEFAULT_ROM.read_bytes()


def v11():
    return Image.from_tape(TAPE_V11)


def v11_rom():
    return ROM_V11.read_bytes()


def default():
    return Image.from_tape(DEFAULT_TAPE)
