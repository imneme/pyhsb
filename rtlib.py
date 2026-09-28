"""The runtime library, emitted by the user's own compiler.

HiSoft BASIC doesn't copy its runtime routines from a blob: each routine has
an emitter (a table of 131 addresses), and the emitter is Z80 code that emits
the routine from inline fragments (CALL emit_inline / JR n / n bytes), with
calls in between for the parts that hold addresses (JP PO,RTn and so on).
So the only faithful source of those bytes is the compiler itself.  Here a
small Z80 interpreter (z80mini) runs those emitters out of the user's image,
with the compiler's working variables in its memory, as the real compiler
would have them, and the stub's bank-0 accessors hooked so the bytes land in
a Python buffer.

The layout loop (which routines, in what order, at what address) is ours.
"""
from z80mini import Z80

# Where things are in the v1.2 (128) image.  Addresses, not bytes.
V12 = dict(
    rt_table=0x4000,        # 131 x (used flag, relative address)
    n_rt=131,
    emitter_table=0xE071,   # 131 words: each routine's emitter (0 = empty slot)
    code_pc=0x44EF,         # the generated code's relative program counter
    counting=0x451E,        # 1 in passes 0 and 1, 0 in pass 2
    de_flags=0xF072,        # bit 0: don't store code, bit 1: don't store DATA
    out_base=0xF07F,        # where in bank 0 the code is written
    code_base=0x4517,       # the load address, for relocated words
    # the resident stub's bank-0 accessors (installed at 23792, outside the image)
    far_ldir=0x5E6D, far_lddr=0x5E74, far_put_c=0x5E7B, far_put_a_de=0x5E81,
    far_put_de=0x5E89, far_put_bc=0x5E91,
)

# v1.1 (48K): the compiler runs where it loads (0x5CF0..0x8B5C) and writes its output
# straight into memory, so there is no stub to hook.  Its emitters write to
# out_base + pc in the interpreter's memory, and we point out_base at a staging area.
V11 = dict(
    rt_table=0x4000, n_rt=131, emitter_table=0x77AF, code_pc=0x44EF, counting=0x451C,
    de_flags=0x889C, out_base=0x88AE, code_base=0x4517,
    direct=True, staging=0x9000,
)


class Machine:
    """The compiler's memory as the emitters see it, plus the target's RAM."""

    def __init__(self, img, rom, profile=None):
        """img: the compiler (hbcimage.Image); rom: the 16K ROM that is paged
        while it compiles (ROM 1 of a 128: some routines are copied from it)."""
        self.img = img
        if profile is None:
            profile = V11 if getattr(img, 'v11', False) else V12
        self.p = profile
        self.mem = bytearray(65536)
        if len(rom) != 16384:
            raise ValueError(f'the ROM should be 16,384 bytes, not {len(rom)}')
        self.mem[0:16384] = rom
        img.load_into(self.mem)
        self.far = bytearray(65536)          # the target: code lands at out_base + pc
        self.cpu = Z80(self.mem)
        self.cpu.sp = 0x5A00                 # the compiler's own stack, in the attribute file
        p, c, far = self.p, self.cpu, self.far

        def ldir(cpu):
            while True:
                far[cpu.de] = cpu.mem[cpu.hl]        # source: the bounce buffer, in the display file
                cpu.hl = (cpu.hl + 1) & 0xFFFF; cpu.de = (cpu.de + 1) & 0xFFFF
                cpu.bc = (cpu.bc - 1) & 0xFFFF
                if cpu.bc == 0:
                    break

        def put_c(cpu):
            far[cpu.hl] = cpu.c

        def put_a_de(cpu):
            far[cpu.de] = cpu.a

        def put_de(cpu):
            far[cpu.hl] = cpu.e; cpu.hl = (cpu.hl + 1) & 0xFFFF; far[cpu.hl] = cpu.d

        def put_bc(cpu):
            far[cpu.hl] = cpu.c; cpu.hl = (cpu.hl + 1) & 0xFFFF; far[cpu.hl] = cpu.b

        def lddr(cpu):
            # no emitter copies backwards; the compiler uses LDDR only to move its finished
            # code (the 'delete the BASIC?' path), which pyhsb doesn't take
            raise NotImplementedError('far LDDR')

        if not p.get('direct'):
            c.hooks.update({p['far_ldir']: ldir, p['far_lddr']: lddr, p['far_put_c']: put_c,
                            p['far_put_a_de']: put_a_de, p['far_put_de']: put_de, p['far_put_bc']: put_bc})

    # -- the compiler's variables ----------------------------------------------------
    def w(self, a):
        return self.mem[a] | self.mem[a + 1] << 8

    def setw(self, a, v):
        self.mem[a] = v & 0xFF
        self.mem[a + 1] = (v >> 8) & 0xFF

    # -- the routine table ------------------------------------------------------------
    def clear_table(self):
        t = self.p['rt_table']
        self.mem[t:t + 3 * self.p['n_rt']] = bytes(3 * self.p['n_rt'])

    def used(self, n):
        return self.mem[self.p['rt_table'] + 3 * (n - 1)] != 0

    def rt_addr(self, n):
        """relative address of RTn (as laid out in the last pass)"""
        return self.w(self.p['rt_table'] + 3 * (n - 1) + 1)

    def use(self, n):
        """mark RTn used, return its relative address (0xC581)"""
        t = self.p['rt_table'] + 3 * (n - 1)
        self.mem[t] = 1
        return self.w(t + 1)

    def emitter(self, n):
        return self.img.word(self.p['emitter_table'] + 2 * (n - 1))

    # -- emitting ---------------------------------------------------------------------
    def run_emitter(self, n, pc, counting, code_base):
        """Run RTn's emitter with the code PC at pc.  Returns the new pc."""
        p = self.p
        self.setw(p['code_pc'], pc)
        self.mem[p['counting']] = 1 if counting else 0
        self.mem[p['de_flags']] = 0
        direct = p.get('direct')
        self.setw(p['out_base'], p['staging'] if direct else 0)
        self.setw(p['code_base'], code_base)
        addr = self.emitter(n)
        if addr == 0:
            raise ValueError(f'RT{n} is an empty slot')
        self.cpu.sp = 0x5A00
        self.cpu.call(addr)
        end = self.w(p['code_pc'])
        if direct and not counting:
            st = p['staging']
            self.far[pc:end] = self.mem[st + pc:st + end]
        return end

    def layout(self, pc, counting, code_base):
        """The layout loop (0xDFB6): each marked routine, in number order, gets
        the current pc as its address and is emitted.  Emitters may mark more
        routines (a routine that falls into the next one marks it)."""
        t = self.p['rt_table']
        for n in range(1, self.p['n_rt'] + 1):
            if self.mem[t + 3 * (n - 1)]:
                self.setw(t + 3 * (n - 1) + 1, pc)
                pc = self.run_emitter(n, pc, counting, code_base)
        return pc
