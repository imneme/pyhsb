"""Compile-time floating point, done by the ROM's own calculator.

HiSoft BASIC does a little arithmetic while compiling (a unary minus folded
into a literal, rounding a constant to an integer, DEC_TO_FP for VAL "..."
and for directive numbers), always with the ROM.  To get the same bits,
pyhsb runs the same ROM routines in z80mini, on the user's ROM.  Small
integers (the ROM's 'integer form') take a Python fast path, checked
against the ROM in tests/test_romfp.py.
"""
from z80mini import Z80Error

STKBOT, STKEND, CH_ADD, MEM, BREG = 0x5C63, 0x5C65, 0x5C5D, 0x5C68, 0x5C67
STACK_AT = 0x5800           # the compiler keeps its calculator stack in the attribute file
CODE_AT = 0x5B80            # where we put a little calculator program
MEMBOT = 0x5C92
TEXT_AT = 0x45A9            # the compiler's line buffer: DEC_TO_FP reads from here

# The ROM calculator's documented opcodes (Sinclair's interface, not HiSoft's).
C_JUMP_TRUE, C_EXCHANGE, C_DELETE, C_SUBTRACT, C_MULTIPLY, C_DIVISION = 0x00, 0x01, 0x02, 0x03, 0x04, 0x05
C_ADDITION, C_NEGATE, C_DUPLICATE, C_LESS_0, C_JUMP, C_END = 0x0F, 0x1B, 0x31, 0x36, 0x33, 0x38
C_TRUNCATE, C_STK_HALF = 0x3A, 0xA2
TRUNCATE = 0x3214           # calc:truncate, called directly by the compiler
DEC_TO_FP = 0x2C9B


class ROMError(Exception):
    def __init__(self, code):
        super().__init__(f'ROM error {code}')
        self.code = code        # the RST 8 byte: 0x0A is report B, integer out of range


def is_int_form(x):
    return x[0] == 0 and x[1] in (0, 0xFF) and x[4] == 0


def int_value(x):
    v = x[2] | x[3] << 8
    return v - 65536 if x[1] == 0xFF else v


def int_form(v):
    """-65535..65535 in the ROM's integer form (negative: sign FF, two's complement)."""
    return bytes([0, 0xFF if v < 0 else 0, v & 0xFF, (v >> 8) & 0xFF, 0])


class ROMFP:
    def __init__(self, machine):
        self.m = machine
        self.cpu = machine.cpu
        self.mem = machine.mem
        self.cpu.hooks[0x0008] = self._error
        self.calls = 0

    def _error(self, cpu):
        ret = cpu.rw(cpu.sp)
        raise ROMError(cpu.rb(ret))

    def _setup(self, stack):
        mem, m = self.mem, self.m
        m.setw(STKBOT, STACK_AT)
        p = STACK_AT
        for x in stack:
            mem[p:p + 5] = x
            p += 5
        m.setw(STKEND, p)
        m.setw(MEM, MEMBOT)
        self.cpu.iy = 0x5C3A
        self.cpu.sp = 0x5A00

    def _stack(self):
        m = self.m
        bot, end = m.w(STKBOT), m.w(STKEND)
        return [bytes(self.mem[a:a + 5]) for a in range(bot, end, 5)]

    def calc(self, stack, ops):
        """Run RST 28 / ops / end-calc on the given stack (a list of 5-byte values)."""
        self.calls += 1
        self._setup(stack)
        prog = bytes([0xEF]) + bytes(ops) + bytes([C_END, 0xC9])
        self.mem[CODE_AT:CODE_AT + len(prog)] = prog
        self.cpu.call(CODE_AT)
        return self._stack()

    # -- what the compiler needs -----------------------------------------------------
    def negate(self, x):
        """calc negate (the compiler folds a unary minus into a literal: 0xCA44)."""
        if is_int_form(x):
            v = int_value(x)
            if v == 0:
                return bytes(x)
            return int_form(-v)
        return self.calc([x], [C_NEGATE])[0]

    def round_to_hl(self, x):
        """0xCA19: add or subtract 0.5, truncate, and take the integer form's
        word (error B if not an integer in -65535..65535).  Returns 0..65535."""
        if is_int_form(x):
            return (x[2] | x[3] << 8)
        st = self.calc([x], [C_DUPLICATE, C_LESS_0, C_JUMP_TRUE, 5, C_STK_HALF, C_ADDITION,
                             C_JUMP, 3, C_STK_HALF, C_SUBTRACT])
        return self.truncate_to_hl(st[-1])

    def truncate_to_hl(self, x):
        """0xEBF5: calc:truncate, then the value must be in integer form."""
        self.calls += 1
        self._setup([x])
        self.m.setw(0x5C65, STACK_AT + 5)
        # TRUNCATE is entered with HL pointing at the value, DE at STKEND (as RST 28 would)
        self.cpu.hl = STACK_AT
        self.cpu.de = STACK_AT + 5
        self.cpu.call(TRUNCATE)
        y = bytes(self.mem[STACK_AT:STACK_AT + 5])
        if y[0] != 0:
            raise ROMError(0x0A)
        return y[2] | y[3] << 8

    def dec_to_fp(self, text, pos, at=TEXT_AT):
        """DEC_TO_FP on text (a line, from its start) from index pos: returns (the 5-byte
        number, the index after it).  The line is put at `at` first, up to its CR (the
        number ends before that): v1.2's line buffer, or, for v1.1, which reads lines where
        they are, the line's own place in the program.  (Never more: copied whole, v1.1's
        'buffer' is the rest of the program, and lands on its line table and its code.)"""
        self.calls += 1
        end = text.find(0x0D, pos)
        end = len(text) if end < 0 else end + 1
        self.mem[at:at + end] = text[:end]
        self._setup([])
        self.m.setw(CH_ADD, at + pos)
        self.cpu.a = text[pos]
        self.cpu.hl = at + pos
        self.cpu.call(DEC_TO_FP)
        return self._stack()[-1], self.m.w(CH_ADD) - at
