"""A small Z80 interpreter: enough to run pieces of the user's own compiler
(its runtime-library emitters) with some addresses hooked by Python.

Not cycle-accurate, no interrupts, no undocumented flag bits (3 and 5).  It
decodes by the usual x/y/z/p/q fields, so it covers the whole unprefixed,
CB, ED and DD/FD sets rather than a hand-picked list.  I/O and HALT raise.

    cpu = Z80(mem)                 # mem: a bytearray(65536)
    cpu.hooks[0xC4B9] = fn         # fn(cpu) runs instead of the code there, then RET
    cpu.call(0xE825)               # run until the call returns
"""

S, Z, H, PV, N, C = 0x80, 0x40, 0x10, 0x04, 0x02, 0x01


def parity(v):
    v ^= v >> 4
    v ^= v >> 2
    v ^= v >> 1
    return 0 if v & 1 else PV


class Z80Error(Exception):
    pass


class Z80:
    def __init__(self, mem):
        self.mem = mem
        self.a = self.f = self.b = self.c = self.d = self.e = self.h = self.l = 0
        self.ix = self.iy = 0
        self.sp = 0xFF00
        self.pc = 0
        self.alt = [0] * 8          # A' F' B' C' D' E' H' L'
        self.hooks = {}             # address -> fn(cpu); acts as a routine: we RET after it
        self.steps = 0
        self.limit = 200000
        self.trace = None           # fn(pc) called before each instruction, if set

    # -- registers ---------------------------------------------------------------
    @property
    def bc(self): return self.b << 8 | self.c
    @bc.setter
    def bc(self, v): self.b, self.c = (v >> 8) & 0xFF, v & 0xFF
    @property
    def de(self): return self.d << 8 | self.e
    @de.setter
    def de(self, v): self.d, self.e = (v >> 8) & 0xFF, v & 0xFF
    @property
    def hl(self): return self.h << 8 | self.l
    @hl.setter
    def hl(self, v): self.h, self.l = (v >> 8) & 0xFF, v & 0xFF
    @property
    def af(self): return self.a << 8 | self.f
    @af.setter
    def af(self, v): self.a, self.f = (v >> 8) & 0xFF, v & 0xFF

    # -- memory ------------------------------------------------------------------
    def rb(self, a):
        return self.mem[a & 0xFFFF]

    def wb(self, a, v):
        self.mem[a & 0xFFFF] = v & 0xFF

    def rw(self, a):
        return self.rb(a) | self.rb(a + 1) << 8

    def ww(self, a, v):
        self.wb(a, v); self.wb(a + 1, v >> 8)

    def fetch(self):
        v = self.rb(self.pc); self.pc = (self.pc + 1) & 0xFFFF
        return v

    def fetchw(self):
        v = self.rw(self.pc); self.pc = (self.pc + 2) & 0xFFFF
        return v

    def push(self, v):
        self.sp = (self.sp - 2) & 0xFFFF
        self.ww(self.sp, v)

    def pop(self):
        v = self.rw(self.sp); self.sp = (self.sp + 2) & 0xFFFF
        return v

    # -- running -----------------------------------------------------------------
    SENTINEL = 0x0000

    def call(self, addr, sentinel=0xFFFE):
        """Run a subroutine at addr until it returns to `sentinel`."""
        self.push(sentinel)
        self.pc = addr
        n = 0
        while self.pc != sentinel:
            self.step()
            n += 1
            if n > self.limit:
                raise Z80Error(f'no return after {n} steps (pc={self.pc:04X})')

    def step(self):
        pc = self.pc
        if pc in self.hooks:
            self.hooks[pc](self)
            self.pc = self.pop()
            return
        if self.trace:
            self.trace(pc)
        self.steps += 1
        op = self.fetch()
        if op == 0xCB:
            self.cb(self.fetch(), None)
        elif op == 0xED:
            self.ed(self.fetch())
        elif op in (0xDD, 0xFD):
            self.index(op)
        else:
            self.main(op, None)

    # -- operand access for r[z] with optional index ------------------------------
    def get_r(self, r, idx=None, disp=0):
        if r == 0: return self.b
        if r == 1: return self.c
        if r == 2: return self.d
        if r == 3: return self.e
        if r == 4: return (getattr(self, idx) >> 8) if idx else self.h
        if r == 5: return (getattr(self, idx) & 0xFF) if idx else self.l
        if r == 6: return self.rb(((getattr(self, idx) + disp) if idx else self.hl) & 0xFFFF)
        return self.a

    def set_r(self, r, v, idx=None, disp=0):
        v &= 0xFF
        if r == 0: self.b = v
        elif r == 1: self.c = v
        elif r == 2: self.d = v
        elif r == 3: self.e = v
        elif r == 4:
            if idx: setattr(self, idx, (getattr(self, idx) & 0xFF) | v << 8)
            else: self.h = v
        elif r == 5:
            if idx: setattr(self, idx, (getattr(self, idx) & 0xFF00) | v)
            else: self.l = v
        elif r == 6: self.wb(((getattr(self, idx) + disp) if idx else self.hl) & 0xFFFF, v)
        else: self.a = v

    def get_rp(self, p, idx=None):
        if p == 0: return self.bc
        if p == 1: return self.de
        if p == 2: return getattr(self, idx) if idx else self.hl
        return self.sp

    def set_rp(self, p, v, idx=None):
        v &= 0xFFFF
        if p == 0: self.bc = v
        elif p == 1: self.de = v
        elif p == 2:
            if idx: setattr(self, idx, v)
            else: self.hl = v
        else: self.sp = v

    def get_rp2(self, p, idx=None):
        return self.af if p == 3 else self.get_rp(p, idx)

    def set_rp2(self, p, v, idx=None):
        if p == 3: self.af = v & 0xFFFF
        else: self.set_rp(p, v, idx)

    def cond(self, y):
        f = self.f
        return [not f & Z, f & Z, not f & C, f & C, not f & PV, f & PV, not f & S, f & S][y]

    # -- ALU -------------------------------------------------------------------------
    def alu(self, y, v):
        a = self.a
        if y in (0, 1):                     # ADD, ADC
            cy = (self.f & C) if y == 1 else 0
            r = a + v + cy
            f = (r & 0x80) | (0 if r & 0xFF else Z) | ((a ^ v ^ r) & H)
            f |= PV if (~(a ^ v) & (a ^ r) & 0x80) else 0
            f |= C if r > 0xFF else 0
            self.a, self.f = r & 0xFF, f
        elif y in (2, 3, 7):                # SUB, SBC, CP
            cy = (self.f & C) if y == 3 else 0
            r = a - v - cy
            f = (r & 0x80) | (0 if r & 0xFF else Z) | ((a ^ v ^ r) & H) | N
            f |= PV if ((a ^ v) & (a ^ r) & 0x80) else 0
            f |= C if r < 0 else 0
            self.f = f
            if y != 7:
                self.a = r & 0xFF
        elif y == 4:                        # AND
            self.a = r = a & v
            self.f = (r & 0x80) | (0 if r else Z) | H | parity(r)
        elif y == 5:                        # XOR
            self.a = r = a ^ v
            self.f = (r & 0x80) | (0 if r else Z) | parity(r)
        else:                               # OR
            self.a = r = a | v
            self.f = (r & 0x80) | (0 if r else Z) | parity(r)

    def inc8(self, v):
        r = (v + 1) & 0xFF
        self.f = (self.f & C) | (r & 0x80) | (0 if r else Z) | (H if (v & 0xF) == 0xF else 0) | (PV if v == 0x7F else 0)
        return r

    def dec8(self, v):
        r = (v - 1) & 0xFF
        self.f = (self.f & C) | (r & 0x80) | (0 if r else Z) | (H if (v & 0xF) == 0 else 0) | N | (PV if v == 0x80 else 0)
        return r

    def add16(self, a, b):
        r = a + b
        self.f = (self.f & (S | Z | PV)) | (H if ((a ^ b ^ r) >> 8) & H else 0) | (C if r > 0xFFFF else 0)
        return r & 0xFFFF

    def rot(self, y, v):
        cy = self.f & C
        if y == 0: c, r = v >> 7, (v << 1 | v >> 7)          # RLC
        elif y == 1: c, r = v & 1, (v >> 1 | v << 7)         # RRC
        elif y == 2: c, r = v >> 7, (v << 1 | cy)            # RL
        elif y == 3: c, r = v & 1, (v >> 1 | cy << 7)        # RR
        elif y == 4: c, r = v >> 7, v << 1                   # SLA
        elif y == 5: c, r = v & 1, (v >> 1 | (v & 0x80))     # SRA
        elif y == 6: c, r = v >> 7, (v << 1 | 1)             # SLL
        else: c, r = v & 1, v >> 1                           # SRL
        r &= 0xFF
        self.f = (r & 0x80) | (0 if r else Z) | parity(r) | (C if c else 0)
        return r

    # -- the unprefixed set (with idx = 'ix'/'iy' when prefixed) ---------------------
    def main(self, op, idx):
        x, y, z = op >> 6, (op >> 3) & 7, op & 7
        p, q = y >> 1, y & 1

        def disp():
            d = self.fetch()
            return d - 256 if d > 127 else d

        if x == 1:
            if op == 0x76:
                raise Z80Error(f'HALT at {self.pc - 1:04X}')
            if idx and (y == 6 or z == 6):
                d = disp()
                if y == 6: self.set_r(6, self.get_r(z), idx, d)       # LD (ix+d),r (r real)
                else: self.set_r(y, self.get_r(6, idx, d))            # LD r,(ix+d)
            else:
                self.set_r(y, self.get_r(z, idx), idx)
            return
        if x == 2:
            d = disp() if (idx and z == 6) else 0
            self.alu(y, self.get_r(z, idx, d))
            return
        if x == 0:
            if z == 0:
                if y == 0: return                                  # NOP
                if y == 1:                                         # EX AF,AF'
                    self.a, self.alt[0] = self.alt[0], self.a
                    self.f, self.alt[1] = self.alt[1], self.f
                    return
                if y == 2:                                         # DJNZ
                    d = disp(); self.b = (self.b - 1) & 0xFF
                    if self.b: self.pc = (self.pc + d) & 0xFFFF
                    return
                d = disp()
                if y == 3 or self.cond(y - 4):                     # JR / JR cc
                    self.pc = (self.pc + d) & 0xFFFF
                return
            if z == 1:
                if q == 0: self.set_rp(p, self.fetchw(), idx)
                else: self.set_rp(2, self.add16(self.get_rp(2, idx), self.get_rp(p, idx)), idx)
                return
            if z == 2:
                if y == 0: self.wb(self.bc, self.a)
                elif y == 1: self.a = self.rb(self.bc)
                elif y == 2: self.wb(self.de, self.a)
                elif y == 3: self.a = self.rb(self.de)
                elif y == 4: self.ww(self.fetchw(), self.get_rp(2, idx))
                elif y == 5: self.set_rp(2, self.rw(self.fetchw()), idx)
                elif y == 6: self.wb(self.fetchw(), self.a)
                else: self.a = self.rb(self.fetchw())
                return
            if z == 3:
                v = self.get_rp(p, idx)
                self.set_rp(p, v + 1 if q == 0 else v - 1, idx)
                return
            if z in (4, 5):
                d = disp() if (idx and y == 6) else 0
                v = self.get_r(y, idx, d)
                self.set_r(y, self.inc8(v) if z == 4 else self.dec8(v), idx, d)
                return
            if z == 6:
                d = disp() if (idx and y == 6) else 0
                self.set_r(y, self.fetch(), idx, d)
                return
            # z == 7
            a, cy = self.a, self.f & C
            if y == 0: c, a = a >> 7, (a << 1 | a >> 7) & 0xFF        # RLCA
            elif y == 1: c, a = a & 1, (a >> 1 | a << 7) & 0xFF       # RRCA
            elif y == 2: c, a = a >> 7, (a << 1 | cy) & 0xFF          # RLA
            elif y == 3: c, a = a & 1, (a >> 1 | cy << 7) & 0xFF      # RRA
            elif y == 4: raise Z80Error('DAA')
            elif y == 5:                                               # CPL
                self.a = a ^ 0xFF; self.f |= H | N; return
            elif y == 6:                                               # SCF
                self.f = (self.f & (S | Z | PV)) | C; return
            else:                                                      # CCF
                self.f = ((self.f & (S | Z | PV)) | (H if cy else 0)) | (0 if cy else C); return
            self.a = a
            self.f = (self.f & (S | Z | PV)) | (C if c else 0)
            return
        # x == 3
        if z == 0:
            if self.cond(y): self.pc = self.pop()
            return
        if z == 1:
            if q == 0: self.set_rp2(p, self.pop(), idx); return
            if p == 0: self.pc = self.pop(); return                     # RET
            if p == 1:                                                  # EXX
                for i, r in enumerate('bcdehl'):
                    v = getattr(self, r); setattr(self, r, self.alt[2 + i]); self.alt[2 + i] = v
                return
            if p == 2: self.pc = self.get_rp(2, idx); return            # JP (HL)
            self.sp = self.get_rp(2, idx); return                       # LD SP,HL
        if z == 2:
            t = self.fetchw()
            if self.cond(y): self.pc = t
            return
        if z == 3:
            if y == 0: self.pc = self.fetchw(); return                  # JP nn
            if y in (2, 3): raise Z80Error(f'I/O at {self.pc - 1:04X}')
            if y == 4:                                                  # EX (SP),HL
                v = self.rw(self.sp); self.ww(self.sp, self.get_rp(2, idx)); self.set_rp(2, v, idx); return
            if y == 5:                                                  # EX DE,HL
                self.de, self.hl = self.hl, self.de; return
            if y in (6, 7): return                                      # DI / EI
        if z == 4:
            t = self.fetchw()
            if self.cond(y): self.push(self.pc); self.pc = t
            return
        if z == 5:
            if q == 0: self.push(self.get_rp2(p, idx)); return
            if p == 0:
                t = self.fetchw(); self.push(self.pc); self.pc = t; return  # CALL nn
            raise Z80Error('prefix in main')
        if z == 6:
            self.alu(y, self.fetch()); return
        self.push(self.pc); self.pc = y * 8                             # RST

    def cb(self, op, idx, d=0):
        x, y, z = op >> 6, (op >> 3) & 7, op & 7
        if idx:
            v = self.rb((getattr(self, idx) + d) & 0xFFFF)
        else:
            v = self.get_r(z)
        if x == 0:
            r = self.rot(y, v)
        elif x == 1:
            self.f = (self.f & C) | H | (0 if v & (1 << y) else Z | PV) | (S if y == 7 and v & 0x80 else 0)
            return
        elif x == 2:
            r = v & ~(1 << y)
        else:
            r = v | (1 << y)
        if idx:
            self.wb((getattr(self, idx) + d) & 0xFFFF, r)
            if z != 6: self.set_r(z, r)
        else:
            self.set_r(z, r)

    def ed(self, op):
        x, y, z = op >> 6, (op >> 3) & 7, op & 7
        p, q = y >> 1, y & 1
        if x == 1:
            if z == 2:
                hl, v = self.hl, self.get_rp(p)
                cy = self.f & C
                if q == 0:
                    r = hl - v - cy
                    f = N | (C if r < 0 else 0) | (PV if ((hl ^ v) & (hl ^ r) & 0x8000) else 0)
                else:
                    r = hl + v + cy
                    f = (C if r > 0xFFFF else 0) | (PV if (~(hl ^ v) & (hl ^ r) & 0x8000) else 0)
                r &= 0xFFFF
                f |= (S if r & 0x8000 else 0) | (0 if r else Z) | (H if ((hl ^ v ^ r) >> 8) & H else 0)
                self.hl, self.f = r, f
                return
            if z == 3:
                t = self.fetchw()
                if q == 0: self.ww(t, self.get_rp(p))
                else: self.set_rp(p, self.rw(t))
                return
            if z == 4:
                v = self.a; self.a = 0; self.alu(2, v); return             # NEG
            if z == 5:
                self.pc = self.pop(); return                               # RETN/RETI
            if z == 6: return                                              # IM
            if z == 7 and y in (0, 1, 2, 3): return                        # LD I/R,A etc.: ignore
            raise Z80Error(f'ED {op:02X}')
        if x == 2 and z <= 1 and y >= 4:                                   # LDI/LDD/LDIR/LDDR, CPI...
            if z == 0:
                step = 1 if y in (4, 6) else -1
                while True:
                    self.wb(self.de, self.rb(self.hl))
                    self.hl = (self.hl + step) & 0xFFFF
                    self.de = (self.de + step) & 0xFFFF
                    self.bc = (self.bc - 1) & 0xFFFF
                    if y < 6 or self.bc == 0:
                        break
                self.f = (self.f & (S | Z | C)) | (PV if self.bc else 0)
                return
        raise Z80Error(f'ED {op:02X} at {self.pc - 2:04X}')

    def index(self, prefix):
        idx = 'ix' if prefix == 0xDD else 'iy'
        op = self.fetch()
        if op == 0xCB:
            d = self.fetch(); d = d - 256 if d > 127 else d
            self.cb(self.fetch(), idx, d)
            return
        if op in (0xDD, 0xFD, 0xED):
            raise Z80Error('odd prefix')
        if op == 0xEB:                           # EX DE,HL is unaffected
            self.main(op, None); return
        self.main(op, idx)
