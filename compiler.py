"""pyhsb: HiSoft BASIC 128 (v1.2), reimplemented in Python.

A translation of the compiler's logic, routine by routine: each method is
marked with the address of the routine it follows in the original (v1.2,
bank 1), so it can be read side by side with the disassembly.  The
generated code's instructions are written as mnemonics (z80asm); the runtime
library comes from the user's own compiler (rtlib), and compile-time
arithmetic from the user's ROM (romfp).  No HiSoft bytes live here.

    c = Compiler(image, rom)
    r = c.compile(program_bytes)      # -> Result (code, load address, ...)
"""
from dataclasses import dataclass, field

from z80asm import asm
from rtnames import RT
import rtlib
import romfp

# -- tokens and characters --------------------------------------------------------------
T_RND, T_INKEY, T_PI, T_FN, T_POINT, T_SCREEN, T_ATTR, T_AT, T_TAB = 0xA5, 0xA6, 0xA7, 0xA8, 0xA9, 0xAA, 0xAB, 0xAC, 0xAD
T_VALS, T_CODE, T_VAL, T_LEN, T_USR, T_STRS, T_CHRS, T_NOT = 0xAE, 0xAF, 0xB0, 0xB1, 0xC0, 0xC1, 0xC2, 0xC3
T_BIN, T_OR, T_AND, T_LE, T_GE, T_NE, T_LINE, T_THEN, T_TO, T_STEP = 0xC4, 0xC5, 0xC6, 0xC7, 0xC8, 0xC9, 0xCA, 0xCB, 0xCC, 0xCD
T_DEFFN, T_OPEN, T_CLOSE, T_INK, T_OVER, T_LPRINT, T_STOP, T_READ, T_DATA, T_RESTORE = 0xCE, 0xD3, 0xD4, 0xD9, 0xDE, 0xE0, 0xE2, 0xE3, 0xE4, 0xE5
T_REM, T_FOR, T_GOTO, T_GOSUB, T_INPUT, T_LET, T_PRINT, T_PLAY = 0xEA, 0xEB, 0xEC, 0xED, 0xEE, 0xF1, 0xF5, 0xA4
CR = 0x0D

# types (0x453B)
REAL, INTEG, POSINT, BOTH, STRING = 0, 1, 2, 3, 0x80

# ROM addresses the generated code calls (Sinclair's ROM, by name)
ROM = dict(STACK_NUM=0x33B4, SET_WORK=0x16BF, CLS=0x0D6B, PLOT_SUB=0x22E5, PLOT_TEMPS=0x22DF,
           DRAW_LINE=0x24B7, LINE_DRAW=0x2477, DRAW_ARC=0x2394, CIRCLE=0x232D, CO_TEMP=0x1CAD,
           OPEN=0x1736, CLOSE=0x16E5, TEMPS=0x0D4D, PRINT_FP=0x2DE3, STK_STORE=0x2AB6, STK_FETCH=0x2BF1,
           RANDOMIZE0=0x1E56, RANDOMIZE_BC=0x1E52, BORDER=0x2297, CHAN_OPEN=0x1601, STRS_ADD=0x359C,
           TO_POWER=0x3851, INT=0x36AF, LN=0x3713, EXP=0x36C4, SQR=0x384A, SIN=0x37B5, COS=0x37AA,
           TAN=0x37DA, ASN=0x3833, ACS=0x3843, STR=0x361F, CHR=0x35D0, SCREEN=0x2538, LET_STR=0x2B7F,
           ERR_STMT_LOST=0x16)

# Comparison operators -> runtime routine, by the types of the two sides
# (0xD190...: the compiler searches (operator, routine) pairs with the ROM's INDEXER).
CMP_STR = {T_GE: RT.STR_GE, T_LE: RT.STR_LE, ord('<'): RT.STR_LT, ord('>'): RT.STR_GT, T_NE: RT.STR_NE, ord('='): RT.STR_EQ}
CMP_INT_INT = {T_LE: RT.INT_LE, T_GE: RT.INT_GE, ord('>'): RT.INT_GT, ord('<'): RT.INT_LT, ord('='): RT.INT_EQ, T_NE: RT.INT_NE}
CMP_INT_POS = {T_LE: RT.INT_LE_POSINT, T_GE: RT.INT_GE_POSINT, ord('>'): RT.INT_GT_POSINT, ord('<'): RT.INT_LT_POSINT, ord('='): RT.MIXED_EQ, T_NE: RT.MIXED_NE}
CMP_POS_INT = {T_LE: RT.POSINT_LE_INT, T_GE: RT.POSINT_GE_INT, ord('>'): RT.POSINT_GT_INT, ord('<'): RT.POSINT_LT_INT, ord('='): RT.MIXED_EQ, T_NE: RT.MIXED_NE}
CMP_POS_POS = {T_LE: RT.POSINT_LE, T_GE: RT.POSINT_GE, ord('>'): RT.POSINT_GT, ord('<'): RT.POSINT_LT, ord('='): RT.INT_EQ, T_NE: RT.INT_NE}
# the ROM calculator's comparison opcodes (no-l-eql .. nos-eql), as the ROM's operator table gives them
CMP_CALC = {T_LE: 0x09, T_GE: 0x0A, T_NE: 0x0B, ord('>'): 0x0C, ord('<'): 0x0D, ord('='): 0x0E}

# The compiler's messages are numbered 100..111 and printed from a PO_MSG table in the
# image (0xE2EB in v1.2, 0x7A42 in v1.1); a ROM report raised while compiling is
# named by the ROM's own table (0x1391).  pyhsb reads both, so carries no text of theirs.
MSG_TABLE = {False: 0xE2EB, True: 0x7A42}
ROM_REPORTS = 0x1391
ROM_B = 0x0A                   # the RST 8 code of report B, 'Integer out of range'
NOTE_RESETS = ' (the real compiler resets the machine here)'
NOTE_ABANDONS = ' (the real compiler abandons the compile here, back to the editor with no report)'
NOTE_NO_HANDLER = ' (the real compiler has no handler for it: it may reset or report a wrong error)'

PROG_128 = 24259       # PROG on a 128 with the compiler's stub resident
PROG_48 = 35698        # PROG on a 48K with v1.1 resident (CHANS pushed up to 35677)
RAMTOP_X = 65367       # after the compiler's X command (CLEAR 65367)


class CompileError(Exception):
    """code: the compiler's message number (100..109), or ('rom', n, note) for ROM report n.
    The text is filled in by Compiler.message(), from the user's image and ROM."""
    def __init__(self, code, line=None, where=None, detail=''):
        self.code, self.line, self.where, self.detail = code, line, where, detail
        super().__init__(f'error {code}' + (f' at line {line}' if line is not None else '') + (f' ({detail})' if detail else ''))
        self.message = None


@dataclass
class Result:
    ok: bool = False
    error: str = ''
    error_line: int = None
    code: bytes = b''            # the CODE block (main code, runtime, DATA)
    load: int = 0                # where it runs (code_base)
    save: int = 0                # where it was built (out_base)
    var_bytes: int = 0
    basic_bytes: int = 0
    entries: list = field(default_factory=list)   # [(line, address)] of each REM : OPEN #
    unwritten: list = field(default_factory=list)  # code offsets the compiler skips without writing
    rts: list = field(default_factory=list)        # [(n, address)] routines used
    variables: list = field(default_factory=list)  # [(name, type, address)]
    detail: str = ''                               # more about the error, for people
    rom_report: bool = False                       # the error is a ROM report raised while compiling
    v11: bool = False
    # for the printed report and for diagnostics
    printed: list = field(default_factory=list)    # [(line, address)] 'LINE n:' entries, pass 2
    printed1: list = field(default_factory=list)   # [(line, offset)] the same, pass 1
    line_starts: list = field(default_factory=list)  # [(line, offset)] where each line's code starts
    list_directive: int = 0
    arrays: list = field(default_factory=list)     # the array table a..z
    strvars: list = field(default_factory=list)    # the string table a..z


def lc(c):
    return c | 0x20


def letter(c):
    """The index 0..25 of the letter c names (the original's C608: OR 0x20, SUB 'a').
    Anything else would index its per-letter tables out of range."""
    k = (c | 0x20) - 0x61
    if not 0 <= k < 26:
        raise CompileError(103, detail=f'{chr(c)!r} where a letter should be')
    return k


def is_alpha(c):
    return 0x41 <= c <= 0x5A or 0x61 <= c <= 0x7A


def is_digit(c):
    return 0x30 <= c <= 0x39


def is_alnum(c):
    return is_alpha(c) or is_digit(c)


class Compiler:
    def __init__(self, image, rom, ramtop=RAMTOP_X, prog_addr=None, exact=False):
        # v1.1 (the 48K compiler, side A) differs from v1.2 in a handful of places,
        # each marked 'v1.1' below; everything else is the same logic, moved.
        self.v11 = getattr(image, 'v11', False)
        # exact: reproduce the original, bugs and all (the harness always uses this).
        # Otherwise HiSoft's compile-time bugs are fixed; see fix notes by 'self.exact'.
        self.exact = exact
        if prog_addr is None:
            prog_addr = PROG_48 if self.v11 else PROG_128
        # where the line table (F085 / 4541) and the name table (49A9 / 4C4B) live
        self.TABLE, self.TABLE_END = (0x4541, 0x4C4B) if self.v11 else (0xF085, 0xFFFC)
        self.NAMES = 0x4C4B if self.v11 else 0x49A9
        self.m = rtlib.Machine(image, rom)
        self.rom = rom
        self.fp = romfp.ROMFP(self.m)
        self.far = self.m.far
        self.ramtop = ramtop
        self.prog_addr = prog_addr

    # =====================================================================================
    # the source: one line at a time in a buffer, with CH_ADD as an index
    # =====================================================================================
    def skip_over(self, i):
        """ROM TEST_CHAR/SKIP_OVER: index of the next significant character from i."""
        buf = self.buf
        while True:
            c = buf[i]
            if c >= 0x21 or c == CR:
                return i
            if c < 0x10 or c >= 0x18:
                i += 1
            elif c < 0x16:
                i += 2
            else:
                i += 3

    def get_char(self):                  # RST 18
        self.ch = self.skip_over(self.ch)
        return self.buf[self.ch]

    def next_char(self):                 # RST 20
        self.ch = self.skip_over(self.ch + 1)
        return self.buf[self.ch]

    def peek_after(self):                # C578: the byte just after the current character
        self.get_char()
        return self.buf[self.ch + 1]

    def at_end(self):                    # D5E0: Z at ':' or CR
        c = self.get_char()
        return c == ord(':') or c == CR

    def match(self, name, token):
        """CD7F: the token, or the name spelled out (letters in either case,
        spaces allowed between them).  On a match CH_ADD moves past it.
        v1.1 has no CD7F: it compares the token, then NEXT_CHAR."""
        if self.v11:
            if self.get_char() == token:
                self.next_char()
                return True
            return False
        i = self.skip_over(self.ch)
        self.ch = i
        buf = self.buf
        j = i
        for k, ch in enumerate(name.encode()):
            if buf[j] == ch or buf[j] == (ch | 0x20):
                j += 1
                while buf[j] == 0x20:
                    j += 1
            else:
                break
        else:
            self.ch = j
            self.get_char()
            return True
        if buf[i] == token:
            self.ch = i + 1
            self.get_char()
            return True
        return False

    def text_at(self):
        """Where the ROM reads the line being compiled: v1.2's line buffer (0x45A9); v1.1
        compiles lines in place, in the program itself."""
        if self.v11:
            return self.prog_addr + self.line_offsets[self.li] + 4
        return romfp.TEXT_AT

    def error(self, code, detail=''):
        raise CompileError(code, self.line_no, self.ch, detail)

    def not_supported(self, detail=''):   # E177
        self.error(103, detail)

    # =====================================================================================
    # emitting (C4AF..C5E5)
    # =====================================================================================
    @property
    def storing(self):                    # C50A: Z if this pass stores code
        return not self.counting

    def emit_byte(self, a):               # C4B9
        if self.storing:
            self.far[self.pc] = a & 0xFF
        self.pc = (self.pc + 1) & 0xFFFF

    def emit_word(self, v):               # C4B4
        self.emit_byte(v & 0xFF)
        self.emit_byte((v >> 8) & 0xFF)

    def emit_word_reloc(self, v):         # C4AF
        self.emit_word(v + self.code_base)

    def emit_bytes(self, bs):             # C4E8 / C4E1: a fragment copied whole
        if self.storing:
            self.far[self.pc:self.pc + len(bs)] = bs
        self.pc = (self.pc + len(bs)) & 0xFFFF

    def emit(self, text, *vals):          # an inline fragment, as instructions
        self.emit_bytes(asm(text, *vals))

    def emit_opcode(self, text):
        """An instruction's opcode bytes, without its final 2-byte operand ('call nn',
        'jp po,nn', 'ld de,(nn)'): for operands that are relocated or patched later."""
        self.emit_bytes(asm(text.replace('nn', '0'))[:-2])

    def emit_call(self, addr):            # C4DA
        self.emit('call {}', addr)

    def emit_jp(self, addr):              # C4D6
        self.emit('jp {}', addr)

    def rt_use(self, n):                  # C581
        return self.m.use(n)

    def call_rt(self, n):                 # C59D: CALL runtime routine n (and mark it used)
        a = self.rt_use(n)
        self.emit_op_reloc('call nn', a)

    def emit_op_reloc(self, text, addr):  # C5A2: an instruction whose operand is an address in the code
        self.emit_opcode(text)
        self.emit_word_reloc(addr)

    def ld_hl_ind(self, addr):            # C5C4
        self.emit_op_reloc('ld hl,(nn)', addr)

    def ld_de_ind(self, addr):            # C5C8
        self.emit_op_reloc('ld de,(nn)', addr)

    def st_de(self, addr):                # C5D3
        self.emit_op_reloc('ld (nn),de', addr)

    def st_hl(self, addr):                # C5D9
        self.emit_op_reloc('ld (nn),hl', addr)

    def ld_de(self, addr):                # C5DD
        self.emit_op_reloc('ld de,nn', addr)

    def ld_hl(self, addr):                # C5E1
        self.emit_op_reloc('ld hl,nn', addr)

    def ld_bc_abs(self, v):               # C5E5: LD BC,v (not relocated)
        self.emit('ld bc,{}', v)

    def ex_de_hl(self):                   # C4D2
        self.emit('ex de,hl')

    def push_call_pop(self, fn):          # C63B: PUSH HL / (fn) / POP DE
        self.emit('push hl')
        fn()
        self.emit('pop de')

    def push_call_pop_ex(self, fn):       # C648: ... then EX DE,HL
        self.push_call_pop(fn)
        self.ex_de_hl()

    # -- rewinding (C64E, C659, C664) -------------------------------------------------------
    def save_state(self):
        return (self.ch, self.pc)

    def restore_state(self, st):
        self.ch, self.pc = st

    def rewind_code(self, st):
        self.pc = st[1]

    # -- probing (C66C, C67E) -------------------------------------------------------------------
    # To specialise a*2, a+1, INT (a/4) or POKE a,5, the compiler compiles the right operand
    # as a trial (a 'probe': constants and integer variables go to DE), looks at what it was,
    # then rewinds the trial code and emits the special form.  What a probe reports:
    #   probe_simple (0x452B): 0     not simple (anything else ends a probe at once: probe_abort)
    #                          1..3  the integer constant 1, 2 or 3   (INC HL x n, ^2, ^3, x3)
    #                          0x40  another integer constant
    #                          0x80  an integer variable
    #   probe_pow2 (0x452C):   n     the constant is 2^n, n = 1..8 (256 is 8), else 0
    # With no INT directive every constant is REAL, so nothing probes as simple.
    def probe_abort(self):
        """C66C: while probing, anything complicated ends the probe as 'not
        simple' and returns from the level that noticed (True: return now)."""
        if not self.probing:
            return False
        self.probe_simple = 0
        self.probe_pow2 = 0
        return True

    def probe(self, fn):                  # C67E
        self.probing = 1
        fn()
        self.probing = 0

    # =====================================================================================
    # types (C9B8..CA07)
    # =====================================================================================
    def convert_type(self, d):            # C9BD
        h = self.t
        if h == STRING or h == d:
            return
        self.t = d
        if h == REAL:
            self.call_rt(RT.REAL_TO_INT)
        elif d == REAL:
            self.call_rt(RT.STACK_INT if h == INTEG else RT.STACK_POSINT)

    def set_type_to_real(self, a):        # C9B8
        self.t = a
        self.convert_type(REAL)

    def expr_to_target(self):             # C9E2
        self.expr()
        self.convert_type(self.target)

    def expr_real(self):                  # C9EA
        self.expr(); self.convert_type(REAL)

    def expr_integ(self):                 # C9EF
        self.expr(); self.convert_type(INTEG)

    def expr_int(self):                   # C9F6
        self.expr(); self.convert_type(POSINT)

    def power_to_real(self):              # C9FD
        self.expr_power(); self.convert_type(REAL)

    def operand_to_real(self):            # CA02
        self.operand(); self.convert_type(REAL)

    def operand_to_int(self):             # CA07
        self.operand(); self.convert_type(POSINT)

    # =====================================================================================
    # numbers (CA0C..CAF3)
    # =====================================================================================
    def not_number(self):
        """CA0C: C (True) unless the character starts a number ('.', BIN or a digit)."""
        c = self.get_char()
        return not (c == ord('.') or c == T_BIN or is_digit(c))

    def read_number(self):                # CA6B: stack the literal at CH_ADD
        if self.not_number():
            self.error(101)
        if self.number_from_digits:
            x, self.ch = self.fp.dec_to_fp(self.buf, self.ch, self.text_at())
            self.calc.append(x)
            return
        i = self.ch
        while True:
            i += 1
            if self.buf[i] == 0x0E:
                break
        x = bytes(self.buf[i + 1:i + 6])
        self.calc.append(x)
        self.ch = i + 6

    def signed_number(self):              # CA48
        c = self.get_char()
        if c == ord('+'):
            c = self.next_char()
        if c == ord('-'):
            self.next_char()
            self.read_number()
            self.calc[-1] = self.fp.negate(self.calc[-1])
        else:
            self.read_number()
        self.classify_const()

    def number_maybe_val(self):           # CA28: a number, or VAL "number"
        c = self.get_char()
        if c != T_VAL:
            self.signed_number()
            return
        self.number_from_digits = 1
        self.next_char(); self.next_char()
        self.signed_number()
        if self.get_char() != ord('"'):
            self.not_supported('VAL')
        self.next_char()
        self.number_from_digits = 0

    def number_to_hl(self):               # CA16: CA28 then round (pops the number)
        self.number_maybe_val()
        return self.round_pop()

    def round_pop(self):                  # CA19
        x = self.calc.pop()
        try:
            return self.fp.round_to_hl(x)
        except romfp.ROMError as e:
            note = '' if not self.exact else (NOTE_ABANDONS if self.v11 else NOTE_RESETS)
            self.error(('rom', e.code, note), 'a constant beyond -65535..65535')

    def drop_number(self):
        """The compiler read a number, then found it wasn't a constant after all, and
        drops it from the calculator stack by rounding it into HL.  That's harmless
        unless the number is out of range: then the ROM's report B has no handler
        mid-compile, and the 128 resets (v1.1 abandons the compile).  Fixed: just drop it."""
        if self.exact:
            self.round_pop()
        else:
            self.calc.pop()

    def classify_const(self):             # CA5E + C3DD
        x = self.calc[-1]
        c = 0
        if x[0] == 0:
            if x[1] == 0:
                c = 2
            v = x[2] | x[3] << 8
            if c & 2:
                ok = v <= 0x7FFF
            else:
                ok = ((v - 1) & 0xFFFF) >= 0x7FFF   # HL=v-1, 7FFF: no carry means it fits INTEG
            if ok:
                c |= 1
        self.t = self.int_directive & c

    def const_probe_flags(self):          # CA8C
        self.probe_pow2 = 0
        self.probe_simple = 0
        if self.t == REAL:
            return
        self.probe_simple = 0x40
        if not (self.t & 2):
            return
        hl = self.fp.round_to_hl(self.calc[-1])     # (on a duplicate)
        hl = (hl - 1) & 0xFFFF
        if hl >> 8:
            return
        l = (hl + 1) & 0xFF
        if l == 0:                       # 256
            self.probe_pow2 = 8
            return
        if l < 4:
            self.probe_simple = l
        # 2^n for n = 1..7 (B counts down from 7 as C doubles from 0x80... see 0xCAB9)
        b, a = 7, l
        c = 0x80
        while b:
            if a == c:
                break
            a = ((a << 1) | (a >> 7)) & 0xFF
            b -= 1
        self.probe_pow2 = b

    def emit_const(self):                 # CAC7
        if self.t == REAL:
            self.call_rt(RT.STACK_CONST)
            x = self.calc.pop()
            for byte in x:
                self.emit_byte(byte)
            return
        hl = self.round_pop()
        self.emit('ld de,{}' if self.probing else 'ld hl,{}', hl)   # a probe leaves it in DE

    # =====================================================================================
    # variables (CC94..CD6F)
    # =====================================================================================
    def name_lookup(self):
        """CCE3: find the name at CH_ADD in the table of simple variables.
        Returns (index, found, index of the character after the name)."""
        buf = self.buf
        for idx, (name, typ) in enumerate(self.names):
            j = self.ch
            k = 0
            ok = True
            while True:
                c = buf[j]
                if c == 0x20:
                    j += 1
                    continue
                c = c | 0x20
                if not is_alnum(c):
                    ok = k == len(name)
                    break
                if k < len(name) and c == ord(name[k]):
                    k += 1
                    j += 1
                    continue
                ok = False
                break
            if ok:
                self.found = 1
                return idx, True, j
        if len(self.names) >= 256:
            self.error(105)
        self.found = 0
        return len(self.names), False, None

    def name_add(self, typ):              # CD1F: add the name at CH_ADD with this type
        buf = self.buf
        j = self.ch
        name = ''
        while True:
            c = buf[j]
            if c == 0x20:
                j += 1
                continue
            if not is_alnum(c):
                break
            name += chr(c | 0x20)
            j += 1
        if typ == REAL:
            self.n_real += 1
        else:
            self.n_int += 1
        self.names.append((name, typ))
        self.name_bytes += len(name) + 1
        if self.NAMES + self.name_bytes > 0x4FFF:
            self.error(106)
        return j

    def simple_var(self):
        """CCB0: a simple variable: its address (relative to the code) and type."""
        idx, found, end = self.name_lookup()
        if not found:
            end = self.name_add(REAL)
        self.ch = end
        name, typ = self.names[idx]
        self.t = typ & 0x7F
        if idx < self.n_int:
            off = 2 * idx
        else:
            off = 5 * ((idx - self.n_int) & 0xFF) + 2 * self.n_int
        return (off + self.vars_start) & 0xFFFF

    def var_ref(self):
        """CC94: a numeric variable reference.  A single letter may be a DEF FN
        parameter that is bound just now."""
        nxt = self.peek_after()
        if not is_alnum(nxt):
            c = self.get_char()
            p = self.fnparams[letter(c)]
            self.t = p['type']
            if p['num'] != 0xFFFF:
                self.next_char()
                return p['num']
        return self.simple_var()

    def emit_var_load(self, addr):        # CD57
        if self.t == REAL:
            self.ld_hl(addr)
            self.emit_call(ROM['STACK_NUM'])
        elif self.probing:
            self.ld_de_ind(addr)
        else:
            self.ld_hl_ind(addr)

    def var_probe_flags(self):            # CD6F
        self.probe_pow2 = 0
        self.probe_simple = 0 if self.t == REAL else 0x80

    # =====================================================================================
    # the expression compiler (CDAA..D278)
    # =====================================================================================
    def operand(self):                    # CDAA
        while True:
            self.t = REAL
            c = self.get_char()
            if c != ord('+'):
                break
            self.next_char()
        if c == ord('-'):
            self.next_char()
            if not self.not_number():
                save = self.ch
                self.read_number()
                if self.get_char() != ord('^'):
                    self.calc[-1] = self.fp.negate(self.calc[-1])
                    self.classify_const(); self.const_probe_flags(); self.emit_const()
                    return
                self.ch = save
                self.drop_number()           # (0xCDD6: the number is dropped, rounded)
            if self.probe_abort():
                return
            self.expr_power()
            self.emit_negate()
            return
        if not self.not_number():
            self.read_number()
            self.classify_const(); self.const_probe_flags(); self.emit_const()
            return
        if is_alpha(c):
            nxt = self.peek_after()
            if nxt == ord('$'):
                if self.probe_abort():
                    return
                self.string_var_operand()
                self.t = STRING
                self.string_suffix()
                return
            if nxt == ord('('):
                hl = self.array_ref()
                if not self.const_index:
                    if self.probe_abort():
                        return
                    self.call_rt(RT.REAL_ARR_GET if self.t == REAL else RT.INT_ARR_GET)
                    return
                self.var_probe_flags()
                self.emit_var_load(hl)
                return
            addr = self.var_ref()
            self.var_probe_flags()
            self.emit_var_load(addr)
            return
        if self.probe_abort():
            return
        c = self.get_char()
        if c == ord('('):
            self.next_char()
            self.expr()
            self.next_char()
            if self.get_char() != ord('('):
                return
            self.emit_call(ROM['STK_FETCH'])
            self.slice_args()
            self.t = STRING
            self.string_suffix()
            return
        if c == ord('"'):
            self.call_rt(RT.STACK_LIT)
            self.emit_string_inline()
            self.t = STRING
            self.string_suffix()
            return
        if c < T_RND or c >= T_NOT:
            self.not_supported('function')
        self.next_char()
        self.function(c)

    def string_suffix(self):              # CE5A..CE6C: s$(...)(...) slices after a string operand
        while self.get_char() == ord('('):
            self.emit_call(ROM['STK_FETCH'])
            self.slice_args()
            self.t = STRING

    def expr_power(self):                 # CECE
        self.operand()
        while True:
            if self.get_char() != ord('^'):
                return
            if self.probe_abort():
                return
            left_real = self.t == REAL
            left_t = self.t
            self.next_char()
            st = self.save_state()
            self.probe(self.operand)
            ps = self.probe_simple
            if ps == 2:
                self.rewind_code(st)
                self.t = left_t
                if left_real:
                    self.emit('rst $28; defb $31,$04,$38')      # duplicate, multiply, end-calc
                    continue
                self.emit('ld d,h; ld e,l')
                self.call_rt(RT.INT_MUL)
                continue
            if ps == 3:
                self.rewind_code(st)
                self.t = left_t
                self.call_rt(RT.REAL_CUBE if left_real else RT.INT_CUBE)
                continue
            self.restore_state(st)
            self.set_type_to_real(left_t)
            self.operand_to_real()
            self.emit_call(ROM['TO_POWER'])

    def expr_mul(self):                   # CF34
        self.expr_power()
        while True:
            c = self.get_char()
            if c == ord('/'):
                if self.probe_abort():
                    return
                self.convert_type(REAL)
                self.next_char()
                st = self.save_state()
                self.probe(self.expr_power)
                n = (-self.probe_pow2) & 0xFF
                if n:
                    self.rewind_code(st)
                    self.emit('ld a,{}', n)
                    self.call_rt(RT.REAL_SCALE_POW2)
                    self.t = REAL
                    continue
                self.restore_state(st)
                self.power_to_real()
                self.call_rt(RT.REAL_DIV)
                continue
            if c != ord('*'):
                return
            if self.probe_abort():
                return
            self.next_char()
            if self.t == REAL:
                st = self.save_state()
                self.probe(self.expr_power)
                if self.probe_pow2:
                    self.rewind_code(st)
                    self.emit('ld a,{}', self.probe_pow2)
                    self.call_rt(RT.REAL_SCALE_POW2)
                    self.t = REAL
                    continue
                self.restore_state(st)
                self.power_to_real()
                self.call_rt(RT.REAL_MUL)
                continue
            left_t = self.t
            st = self.save_state()
            self.probe(self.expr_power)
            if self.probe_pow2:
                self.rewind_code(st)
                n = self.probe_pow2
                if n == 8:
                    self.emit('ld h,l; ld l,0')
                else:
                    for _ in range(n):
                        self.emit('add hl,hl')
                self.t = left_t
                continue
            if self.probe_simple == 3:
                self.rewind_code(st)
                self.emit('ld d,h; ld e,l; add hl,hl; add hl,de')
                self.t = left_t
                continue
            # CFD8: the general integer multiply
            if not self.probe_simple:
                self.restore_state(st)
                st = self.save_state()
                self.push_call_pop(self.expr_power)
                if self.t == REAL:
                    self.restore_state(st)
                    self.set_type_to_real(left_t)
                    self.power_to_real()
                    self.call_rt(RT.REAL_MUL)
                    continue
            self.call_rt(RT.INT_MUL)
            if left_t == INTEG:
                self.t = INTEG
            continue

    def expr_add(self):                   # D00A
        c = self.get_char()
        if c == T_NOT:
            if self.probe_abort():
                return
            self.next_char()
            self.expr_compare()
            self.call_rt(RT.INT_NOT if self.t != REAL else RT.REAL_NOT)
            self.t = POSINT
            return
        self.expr_mul()
        if self.t == STRING:
            if self.probe_abort():
                return
            while self.get_char() == ord('+'):
                self.next_char()
                self.expr_mul()
                self.emit_call(ROM['STRS_ADD'])
                self.set_work = 1
            return
        while True:
            c = self.get_char()
            if c != ord('+') and c != ord('-'):
                return
            if self.probe_abort():
                return
            plus = self.get_char() == ord('+')
            self.next_char()
            if self.t == REAL:
                self._add_real(plus)
                continue
            left_t = self.t
            st = self.save_state()
            self.probe(self.expr_mul)
            ps = self.probe_simple
            if ps & 3:
                self.rewind_code(st)
                self.t = left_t
                op = 'inc hl' if plus else 'dec hl'
                if not plus:
                    self.t = INTEG
                for _ in range(ps & 3):
                    self.emit(op)
                continue
            if not ps:
                self.restore_state(st)
                st = self.save_state()
                self.push_call_pop(self.expr_mul)
                self.probe_simple = 0
                if self.t == REAL:
                    self.restore_state(st)
                    self.set_type_to_real(left_t)
                    self._add_real(plus)
                    continue
            if left_t == INTEG:
                self.t = INTEG
            if plus:
                self.emit('add hl,de')
            else:
                if not self.probe_simple:
                    self.ex_de_hl()
                self.emit('and a; sbc hl,de')
                self.t = INTEG

    def _add_real(self, plus):            # D05F
        self.expr_mul()
        self.convert_type(REAL)
        self.call_rt(RT.REAL_ADD if plus else RT.REAL_SUB)

    def expr_compare(self):               # D0EF
        self.expr_add()
        while True:
            c = self.get_char()
            if not (0x3C <= c < 0x3F or T_LE <= c < T_LINE):
                return
            if self.probe_abort():
                return
            op = c
            self.next_char()
            if self.t == STRING:
                self.expr_add()
                self.call_rt(CMP_STR[op])
                self.t = POSINT
                continue
            if self.t == REAL:
                self._cmp_real(op)
                continue
            left_t = self.t
            st = self.save_state()
            self.probe(self.expr_add)
            if not self.probe_simple:
                self.restore_state(st)
                st = self.save_state()
                self.push_call_pop_ex(self.expr_add)
                if self.t == REAL:
                    self.restore_state(st)
                    self.set_type_to_real(left_t)
                    self._cmp_real(op)
                    continue
            right_int = self.t == INTEG
            if left_t == INTEG:
                table = CMP_INT_INT if right_int else CMP_INT_POS
            else:
                table = CMP_POS_INT if right_int else CMP_POS_POS
            self.call_rt(table[op])
            self.t = POSINT

    def _cmp_real(self, op):              # D127
        self.expr_add()
        self.convert_type(REAL)
        self.emit('ld b,{}', CMP_CALC[op])
        self.call_rt(RT.REAL_COMPARE)
        self.t = POSINT

    def expr_and(self):                   # D1CC
        self.expr_compare()
        while True:
            if self.get_char() != T_AND:
                return
            if self.probe_abort():
                return
            self.next_char()
            if self.t == STRING:
                self.expr_compare()
                self.call_rt(RT.STR_AND_INT if self.t != REAL else RT.STR_AND_REAL)
                self.t = STRING
                continue
            if self.t == REAL:
                self.expr_compare()
                self.call_rt(RT.REAL_AND_INT if self.t != REAL else RT.REAL_AND)
                self.t = REAL
                continue
            left_t = self.t
            self.emit('push hl')
            self.expr_compare()
            if self.t == REAL:
                self.call_rt(RT.INT_AND_REAL)
            else:
                self.emit('ld a,h; or l; pop de; jr z,+1; ex de,hl')
            self.t = left_t

    def expr(self):                       # D22E
        self.expr_and()
        while True:
            if self.get_char() != T_OR:
                return
            if self.probe_abort():
                return
            self.next_char()
            if self.t == REAL:
                self.expr_and()
                self.call_rt(RT.REAL_OR_INT if self.t != REAL else RT.REAL_OR)
                self.t = REAL
                continue
            left_t = self.t
            self.emit('push hl')
            self.expr_and()
            if self.t == REAL:
                self.call_rt(RT.INT_OR_REAL)
            else:
                self.emit('pop de; ex de,hl; ld a,d; or e; jr z,+3; ld hl,1')
            self.t = left_t

    def emit_negate(self):                # C7D1
        if self.t == REAL:
            self.call_rt(RT.REAL_NEG)
            return
        self.emit('xor a; sub l; ld l,a; sbc a,a; sub h; ld h,a')
        self.t = INTEG

    # =====================================================================================
    # functions (C6C7..C9B5), by token
    # =====================================================================================
    def function(self, tok):
        f = {
            T_RND: lambda: self.call_rt(RT.RND),
            T_INKEY: self.fn_inkey, T_PI: self.fn_pi, T_FN: self.fn_fn, T_POINT: self.fn_point,
            T_SCREEN: self.fn_screen, T_ATTR: self.fn_attr, T_CODE: self.fn_code,
            T_VAL: self.fn_val, T_LEN: self.fn_len, T_USR: self.fn_usr, T_STRS: self.fn_strs,
            T_CHRS: self.fn_chrs,
            0xB2: lambda: self.fn_rom(ROM['SIN']), 0xB3: lambda: self.fn_rom(ROM['COS']),
            0xB4: lambda: self.fn_rom(ROM['TAN']), 0xB5: lambda: self.fn_rom(ROM['ASN']),
            0xB6: lambda: self.fn_rom(ROM['ACS']), 0xB7: self.fn_atn, 0xB8: lambda: self.fn_rom(ROM['LN']),
            0xB9: lambda: self.fn_rom(ROM['EXP']), 0xBA: self.fn_int, 0xBB: lambda: self.fn_rom(ROM['SQR']),
            0xBC: self.fn_sgn, 0xBD: self.fn_abs, 0xBE: self.fn_peek, 0xBF: self.fn_in,
        }.get(tok)
        if tok == T_VALS and not self.v11:
            f = self.fn_vals
        if f is None:
            self.not_supported(f'function {tok:#x}')
        f()

    def fn_rom(self, addr):               # C772..C7AB: LN EXP SQR SIN COS TAN ASN ACS
        self.operand_to_real()
        self.emit_call(addr)

    def fn_atn(self):                     # C766
        self.operand_to_real()
        self.emit('rst $28; defb $24,$38')

    def fn_pi(self):                      # C7C7
        self.emit('rst $28; defb $A3,$38; inc (hl)')

    def fn_strs(self):                    # C7B3
        self.operand_to_real()
        self._string_result(ROM['STR'])

    def _string_result(self, addr):       # C7B9
        self.emit_call(addr)
        self._string_type()

    def _string_type(self):               # C7BC
        self.set_work = 1
        self.t = STRING

    def fn_chrs(self):                    # C847
        self.operand_to_int()
        self.emit('ld a,l')
        self._string_result(ROM['CHR'])

    def fn_code(self):                    # C746
        c = self.get_char()
        if c == ord('"'):
            single, b = self.single_char_string()
            if single:
                self.emit('ld de,{}' if self.probing else 'ld hl,{}', b)      # CAE3
                self.t = POSINT
                return
        self.operand()
        self.call_rt(RT.CODE)
        self.t = POSINT

    def fn_sgn(self):                     # C7EC
        self.operand()
        if self.t == REAL:
            self.call_rt(RT.REAL_SGN)
        else:
            self.call_rt(RT.INT_SGN if self.t == INTEG else RT.INT_TO_BOOL)

    def fn_abs(self):                     # C803
        self.operand()
        if self.t == REAL:
            self.call_rt(RT.REAL_ABS)
        elif self.t == INTEG:
            self.call_rt(RT.INT_ABS)

    def fn_usr(self):                     # C816
        self.operand()
        if self.t == STRING:
            self.call_rt(RT.USR_UDG)
            self.t = POSINT
            return
        self.convert_type(POSINT)
        self.call_rt(RT.USR_CALL)

    def fn_peek(self):                    # C82C
        self.operand_to_int()
        self.emit('ld l,(hl); ld h,0')

    def fn_in(self):                      # C838
        self.operand_to_int()
        self.emit('ld b,h; ld c,l; in l,(c); ld h,0')

    def fn_val(self):                     # C855
        if not self.val_directive:
            self.number_from_digits = 1
            if self.get_char() != ord('"'):
                self.not_supported('VAL')
            self.next_char()
            self.expr()
            self.next_char()
            self.number_from_digits = 0
            return
        self.operand()
        self.call_rt(RT.VAL)
        self.t = REAL

    def fn_vals(self):                    # C87F
        self.operand()
        self.call_rt(RT.VAL_STR)
        self._string_type()

    def fn_len(self):                     # C88A
        self.operand()
        self.emit('call $2BF1; ld h,b; ld l,c')
        self.t = POSINT

    def two_ints_bc(self):                # C89A: two integers, the first in C and the second in B
        self.expr_int()
        self.emit('push hl')
        self.next_char()
        self.expr_int()
        self.emit('pop bc; ld b,l')

    def fn_point(self):                   # C8AE
        self.next_char()
        self.two_ints_bc()
        self.next_char()
        self.call_rt(RT.POINT)

    def fn_screen(self):                  # C8B8
        self.next_char()
        self.two_ints_bc()
        self.next_char()
        self._string_result(ROM['SCREEN'])

    def fn_attr(self):                    # C8C3
        self.next_char()
        self.two_ints_bc()
        self.next_char()
        self.call_rt(RT.ATTR)

    def fn_inkey(self):                   # C8CC
        if self.get_char() == ord('#'):
            self.next_char()
            self.operand_to_real()
            self.emit('rst $28; defb $1A,$38')
        else:
            self.call_rt(RT.INKEY_STR)
        self._string_type()

    def fn_int(self):                     # C8E7
        if self.get_char() != ord('('):
            self._int_general()
            return
        st0 = self.save_state()
        self.next_char()
        self.expr_power()
        if self.t == REAL or self.t == STRING or self.get_char() != ord('/'):
            self.restore_state(st0)
            self._int_general()
            return
        self.next_char()
        left_integ = self.t == INTEG
        left_t = self.t
        st = self.save_state()
        self.probe(self.expr_power)
        n = self.probe_pow2
        if n:
            self.rewind_code(st)
            self.t = left_t
            if left_integ:
                if n == 1:
                    self.emit('sra h; rr l')
                else:
                    self.emit('ld b,{}', n)
                    self.call_rt(RT.INT_SHR)
            else:
                if n == 1:
                    self.emit('srl h; rr l')
                elif n == 8:
                    self.emit('ld l,h; ld h,0')
                else:
                    self.emit('ld b,{}', n)
                    self.call_rt(RT.POSINT_SHR)
        else:
            if not self.probe_simple:
                self.restore_state(st)
                self.push_call_pop_ex(self.expr_power)
            if self.t == REAL:
                self.restore_state(st0)
                self._int_general()
                return
            if self.t == INTEG:
                self.call_rt(RT.POSINT_DIV_INT if not left_integ else RT.INT_DIV)
            else:
                self.t = left_t
                self.call_rt(RT.POSINT_DIV if not left_integ else RT.INT_DIV_POSINT)
        if self.get_char() != ord(')'):
            self.restore_state(st0)
            self._int_general()
            return
        self.next_char()

    def _int_general(self):               # C9AB
        self.operand()
        if self.t == REAL:
            self.emit_call(ROM['INT'])

    # =====================================================================================
    # strings (CAF3..CBE1, CE00..CE25, C520, D5E7)
    # =====================================================================================
    def single_char_string(self):
        """D5E7: at '"': is it a one-character literal (not "" or "x""..." or "x"(...)?
        Returns (True, char) and moves past it, or (False, None)."""
        self.get_char()
        i = self.ch
        buf = self.buf
        if buf[i + 1] == ord('"'):
            return False, None
        b = buf[i + 1]
        if buf[i + 2] != ord('"'):
            return False, None
        if buf[i + 3] in (ord('('), ord('"')):
            return False, None
        self.ch = i + 3
        return True, b

    def emit_string_inline(self):         # C520: 2-byte length then the text, "" as one quote
        start = self.pc
        self.emit_word(start)
        n = 0
        self.get_char()
        i = self.ch
        buf = self.buf
        while True:
            i += 1
            if buf[i] == ord('"'):
                i += 1
                if buf[i] != ord('"'):
                    break
            self.emit_byte(buf[i])
            n += 1
        self.ch = i
        if self.storing:
            self.far[start] = n & 0xFF
            self.far[start + 1] = (n >> 8) & 0xFF

    def strvar_default_len(self, sv):     # CAF3
        if self.pass0 or sv['flags']:
            return
        if sv['last']:
            return
        sv['last'] = self.default_len

    def string_var_operand(self):         # CE02..CE23
        c = self.get_char()
        p = self.fnparams[letter(c)]
        self.next_char(); self.next_char()
        if p['str'] != 0xFFFF:
            self._fn_string_param(p['str'])
            return
        sv = self.strvars[letter(c)]
        self.string_var_value(sv)

    def _fn_string_param(self, addr):     # CB7A
        self.ld_hl(addr)
        if self.get_char() != ord('('):
            self.emit_call(ROM['STACK_NUM'])
            return
        self.call_rt(RT.STR_DESC_AT)
        self.slice_args()

    def string_var_value(self, sv):       # CB08
        addr = sv['addr']
        if not sv['first']:
            self.strvar_default_len(sv)
            self.ld_hl(addr)
            if self.get_char() != ord('('):
                self.call_rt(RT.STR_VAR_STACK)
                return
            self.call_rt(RT.STR_VAR_GET)
            self.slice_args()
            return
        # a string array (DIM a$(n,m)): a$(i), a$(i, slice)   (CB2E)
        self.next_char()
        if not self.not_number():
            st = self.save_state()
            self.read_number()
            c = self.get_char()
            if c == ord(')') or c == ord(','):
                ln = sv['last']
                self.ld_bc_abs(ln)
                i = self.round_pop()
                off = (((i - 1) & 0xFFFF) * ln) & 0xFFFF           # EED6
                self.ld_de((off + addr + 2) & 0xFFFF)
                self._strarr_tail()
                return
            self.restore_state(st)
            self.drop_number()                           # (0xCB63)
        self.expr_int()
        self.ld_de(addr)
        self.call_rt(RT.STR_ARR_ELEM)
        self._strarr_tail()

    def _strarr_tail(self):               # CB72
        if self.get_char() == ord(','):
            self.slice_args(at_cb90=True)
            return
        self.next_char()
        self.slice_args()

    def slice_args(self, at_cb90=False):  # CB8B: (a TO b) and friends after a string
        if not at_cb90 and self.get_char() != ord('('):
            self.emit_call(ROM['STK_STORE'])
            return
        while True:
            c = self.next_char()
            if c == ord(')'):
                self.next_char()
                break
            if c == T_TO:
                c = self.next_char()
                if c == ord(')'):
                    self.next_char()
                    break
                self.emit('push de')                  # ( TO b)
                self.expr_int()
                self.next_char()
                self.call_rt(RT.STR_SLICE_TO)
                return
            self.emit('push de; push bc')
            self.expr_int()
            c = self.get_char()
            if c == ord(')'):
                self.next_char()
                self.call_rt(RT.STR_CHAR)
                return
            if c == ord(','):
                continue                              # (0xCBCA: back to CB90)
            c = self.next_char()                      # TO
            if c == ord(')'):
                self.next_char()
                self.call_rt(RT.STR_SLICE_FROM)
                return
            self.emit('push hl')
            self.expr_int()
            self.next_char()
            self.call_rt(RT.STR_SLICE)
            return
        self.emit_call(ROM['STK_STORE'])

    # =====================================================================================
    # arrays (CBE4)
    # =====================================================================================
    def array_ref(self):
        """CBE4: a numeric array element.  Returns the element's address when
        the indexes are constants (self.const_index = 1), otherwise emits code
        leaving the address in HL (and returns None)."""
        self.const_index = 0
        c = self.get_char()
        arr = self.arrays[letter(c)]
        base = arr['addr']
        self.next_char(); self.next_char()
        if not self.not_number():
            st = self.save_state()
            self.read_number()
            c = self.get_char()
            if c == ord(')'):
                self.next_char()
                self.const_index = 1
                hl = self.round_pop()
                self.t = arr['type']
                if self.t == REAL:
                    return (((hl - 1) & 0xFFFF) * 5 + base) & 0xFFFF       # EC53
                return (((hl - 1) & 0xFFFF) * 2 + base) & 0xFFFF
            if c == ord(','):
                self.next_char()
                hl = self.round_pop()
                hl = (hl - 1) & 0xFFFF
                hl = (hl * arr['last']) & 0xFFFF                         # EED6 (ix+3: the last dimension)
                hl = (hl * (2 if arr['type'] != REAL else 5)) & 0xFFFF
                pushed = (hl + base) & 0xFFFF
                return self._array_rest(arr, pushed)
            self.restore_state(st)
            self.drop_number()                           # (0xCC49)
        return self._array_rest(arr, base)

    def _array_rest(self, arr, pushed):   # CC4C..CC93
        if not self.probing:
            self.expr_int()
            if self.get_char() == ord(','):
                self.next_char()
                self.emit('dec hl; ld de,{}', arr['last'])
                self.call_rt(RT.INT_MUL)
                self.push_call_pop(self.expr_int)
                self.emit('add hl,de')
            if self.get_char() != ord(')'):
                self.not_supported('array')
            self.next_char()
            self.t = arr['type']
        self.ld_de(pushed)
        self.const_index = 0
        return None


    # =====================================================================================
    # DEF FN and FN (DB9A, C6CC, C6E5)
    # =====================================================================================
    def fn_entry(self):                   # C6CC: FN letter[$] -> its entry
        c = self.get_char()
        k = letter(c)
        c = self.next_char()
        if c == ord('$'):
            self.next_char()
            return self.strfns[k]
        return self.numfns[k]

    def fn_fn(self):                      # C6E5
        fe = self.fn_entry()
        hl = fe['addr']
        ptypes = fe['ptypes']
        c = self.next_char()
        while c != ord(')'):
            self.expr()
            ptypes = ((ptypes << 2) | (ptypes >> 6)) & 0xFF
            pt = ptypes & 3
            self.convert_type(pt)
            if pt == 0:
                self.ld_de(hl)
                self.call_rt(RT.REAL_STORE)
                hl += 5
            else:
                self.st_hl(hl)
                hl += 2
            c = self.get_char()
            if c != ord(','):
                break
            c = self.next_char()
        self.next_char()
        self.emit_op_reloc('call nn', hl)
        self.t = fe['type']

    def clear_fn_params(self):            # DC3E
        for p in self.fnparams:
            p['num'] = 0xFFFF
            p['str'] = 0xFFFF

    def st_deffn(self):                   # DB9A
        jp_at = self.pc
        self.emit('jp 0')
        fe = self.fn_entry()
        fe['addr'] = self.pc
        count = 0
        c = self.next_char()
        while c != ord(')'):
            c = self.get_char()
            p = self.fnparams[letter(c)]
            count += 1
            i = self.ch
            if self.buf[i + 1] == ord('$'):
                p['str'] = self.pc
                i += 1
                a = STRING
            else:
                p['num'] = self.pc
                a = p['type']
            # two bits of the parameter's type into the FN's type byte (DBE5)
            b0, b1 = a & 1, (a >> 1) & 1
            fe['ptypes'] = ((((fe['ptypes'] << 1) | b0) << 1) | b1) & 0xFF
            size = 5 if a in (STRING, REAL) else 2
            if not self.counting:
                self.unwritten.append((self.pc, size))
            self.pc = (self.pc + size) & 0xFFFF       # the parameter lives here: skipped, not written
            self.ch = i + 7                           # past the hidden 0E and 5 bytes
            c = self.buf[self.ch]
            if c != ord(','):
                break
            c = self.next_char()
        self.next_char()
        if count < 4:                                 # DC4F
            fe['ptypes'] = (fe['ptypes'] << (8 - 2 * count)) & 0xFF
        self.next_char()
        self.target = fe['type']
        self.expr_to_target()
        self.emit('ret')
        if self.storing:
            v = (self.pc + self.code_base) & 0xFFFF
            self.far[jp_at + 1] = v & 0xFF
            self.far[jp_at + 2] = v >> 8
        self.clear_fn_params()

    # =====================================================================================
    # statements
    # =====================================================================================
    def st_stop(self):                    # DCF1
        self.emit('ld hl,$2758; exx; ret')

    def st_return(self):                  # DC6E
        self.emit('ret')

    def st_cls(self):                     # DCFC
        self.emit_call(ROM['CLS'])
        self.call_rt(RT.STREAM_SCREEN)

    def st_beep(self):                    # DC62
        self.expr_real(); self.next_char(); self.expr_real()
        if self.v11:
            self.emit_call(0x03F8)                      # v1.1: the ROM's BEEP
        else:
            self.call_rt(RT.BEEP)

    def st_pause(self):                   # DC73
        self.expr_int(); self.call_rt(RT.PAUSE)

    def st_border(self):                  # DC7B
        self.expr_int()
        self.emit('ld a,l; call $2297')

    def st_out(self):                     # DC88
        self.expr_int()
        self.emit('push hl')
        self.next_char()
        self.expr_int()
        self.emit('pop bc; out (c),l')

    def st_poke(self):                    # DC9D
        self.expr_int()
        self.next_char()
        st = self.save_state()
        self.probe(self.expr_int)
        ps = self.probe_simple
        if ps and not (ps & 0x80):
            self.restore_state(st)
            n = self.number_to_hl()
            self.emit('ld (hl),{}', n & 0xFF)
            return
        if not ps:
            self.restore_state(st)
            self.push_call_pop_ex(self.expr_int)
        self.emit('ld (hl),e')

    def st_copy(self):                    # DCD5
        if self.v11:
            self.emit_call(0x0EAC)                      # v1.1: the ROM's COPY
        else:
            self.call_rt(RT.COPY)

    def st_randomize(self):               # DCDA
        if self.at_end():
            self.emit_call(ROM['RANDOMIZE0'])
            return
        self.expr_int()
        self.emit('ld b,h; ld c,l; call $1E52')

    def colour_item(self, tok):           # DD57
        self.expr_int()
        self.call_rt(RT.INK + (tok - T_INK))         # INK .. OVER: RT116 .. RT121
        self.colours = 1

    def st_colour(self):                  # DD67
        self.colour_item(self.stmt)
        self.emit_call(ROM['CO_TEMP'])

    def colour_prefix(self):              # DD7A: INK 2; PAPER 1; ... before PLOT/DRAW/CIRCLE
        self.colours = 0
        while True:
            c = self.get_char()
            if not (T_INK <= c <= T_OVER):
                return
            self.next_char()
            self.colour_item(c)
            self.next_char()

    def st_plot(self):                    # DD07
        self.colour_prefix()
        self.two_ints_bc()
        self.emit_call(ROM['PLOT_TEMPS'] if self.colours else ROM['PLOT_SUB'])

    def st_draw(self):                    # DD1C
        self.colour_prefix()
        self.expr_real(); self.next_char(); self.expr_real()
        if self.get_char() == ord(','):
            self.next_char()
            self.expr_real()
            self.emit_call(ROM['DRAW_ARC'])
            return
        self.emit_call(ROM['LINE_DRAW'] if self.colours else ROM['DRAW_LINE'])

    def st_circle(self):                  # DD43
        self.colour_prefix()
        self.expr_real(); self.next_char(); self.expr_real(); self.next_char(); self.expr_real()
        self.emit_call(ROM['CIRCLE'])

    def st_open(self):                    # DD8D
        self.expr_real(); self.next_char(); self.expr()
        if not self.at_end():
            self.not_supported('OPEN #')
        self.emit_call(ROM['OPEN'])

    def st_close(self):                   # DDA0
        self.expr_real()
        if not self.at_end():
            self.not_supported('CLOSE #')
        self.emit_call(ROM['CLOSE'])

    def st_play(self):                    # DDAF
        n = 0
        while True:
            self.expr()
            n += 1
            if self.get_char() != ord(','):
                break
            self.next_char()
        self.emit('ld b,{}', n & 0xFF)
        self.call_rt(RT.PLAY)

    # -- PRINT (D4CA) ------------------------------------------------------------------------
    def st_print(self):
        self.stream_used = 0          # 4530
        self.colours = 0              # 452F
        self.sep = 0                  # 452E
        if self.stmt == T_LPRINT:
            self.call_rt(RT.STREAM_PRINTER)
            self.stream_used = 1
        while not self.at_end():
            self.print_item()
        if not self.sep:
            self.emit_char(CR)
        if self.stream_used:
            self.call_rt(RT.STREAM_SCREEN)
            return
        if self.colours:
            self.emit_call(ROM['TEMPS'])

    def emit_char(self, c):               # D596
        self.emit('ld a,{}; rst $10', c)

    def print_item(self):                 # D50D
        self.sep = 0
        c = self.get_char()
        if T_INK <= c <= T_OVER:
            self.next_char()
            self.colour_item(c)
            return
        if c == ord('#'):
            if self.input_flag == 1:
                self.input_flag = 0xFF
                self.call_rt(RT.ERR_SP_RESTORE)
            self.next_char()
            self.expr_int()
            self.emit('ld a,l; call $1601')
            self.stream_used = 1
            return
        if c == T_AT:
            self.next_char()
            self.expr_int()
            self.next_char()
            self.push_call_pop(self.expr_int)
            self.call_rt(RT.PRINT_AT)
            return
        if c == T_TAB:
            self.next_char()
            self.expr_int()
            self.call_rt(RT.PRINT_TAB)
            return
        if c in (ord(','), ord("'")):
            self.emit_char(6 if c == ord(',') else CR)
            self.next_char()
            self.sep = 1
            return
        if c == ord(';'):
            self.next_char()
            self.sep = 1
            return
        if c == ord('"'):
            st = self.save_state()
            single, b = self.single_char_string()
            if single:
                if self.print_sep_follows():
                    self.emit_char(b)
                    return
            else:
                self.call_rt(RT.PRINT_LIT)
                self.emit_string_inline()
                if self.print_sep_follows():
                    return
            self.restore_state(st)
        self.expr()
        if self.t == REAL:
            self.emit_call(ROM['PRINT_FP'])
        elif self.t == STRING:
            self.call_rt(RT.PRINT_STR)
        elif self.t == INTEG:
            self.call_rt(RT.PRINT_INT)
        else:
            self.call_rt(RT.PRINT_POSINT)

    def print_sep_follows(self):          # D5D2 (PR_END_Z, then ; , ')
        c = self.get_char()
        return c in (ord(')'), CR, ord(':'), ord(';'), ord(','), ord("'"))

    # -- INPUT, READ, LET (D6E8, D730, D73A) -------------------------------------------------
    def st_input(self):
        self.call_rt(RT.INPUT_TRAP_ON)
        self.call_rt(RT.INPUT_START)
        if not self.v11:
            self.input_flag = 1
        while True:
            if self.at_end():
                self.call_rt(RT.INPUT_TRAP_OFF)
                self.set_work = 0
                self.input_flag = 0
                return
            c = self.get_char()
            if c == T_LINE:
                self.next_char()
                continue
            if is_alpha(c):
                self.st_let()
                continue
            if c == ord('('):
                self.next_char()
                while self.get_char() != ord(')'):
                    self.print_item()
                self.next_char()
                continue
            self.print_item()

    def st_read(self):
        while True:
            self.st_let()
            if self.get_char() != ord(','):
                return
            self.next_char()

    def let_value(self):                  # D765: where the value comes from
        if self.stmt == T_LET:
            self.next_char()
            self.expr()
            self.convert_type(self.target)
        elif self.stmt == T_READ:
            self.call_rt(RT.READ_REAL if self.target == REAL else RT.READ_INT)
        else:
            self.call_rt(RT.INPUT_REAL if self.target == REAL else RT.INPUT_INT)

    def let_string_value(self):           # D7DA
        if self.stmt == T_LET:
            self.next_char()
            self.expr()
        else:
            self.call_rt(RT.READ_STR if self.stmt == T_READ else RT.INPUT_STR)

    def st_let(self):                     # D73A
        nxt = self.peek_after()
        if nxt == ord('$'):
            self._let_string()
            return
        if nxt == ord('('):
            addr = self.array_ref()
            if not self.const_index:
                self.target = self.t
                if self.t == REAL:
                    self.call_rt(RT.REAL_ARR_ADDR)
                    self.emit('push hl')
                    self.let_value()
                    self.emit('pop de')
                    self.call_rt(RT.REAL_STORE)
                    return
                self.emit('dec hl; add hl,hl; add hl,de; push hl')
                self.let_value()
                self.emit('ex de,hl; pop hl; ld (hl),e; inc hl; ld (hl),d')
                return
        else:
            addr = self.var_ref()
        self.target = self.t
        self.let_value()
        if self.target != REAL:
            self.st_hl(addr)
        else:
            self.ld_de(addr)
            self.call_rt(RT.REAL_STORE)

    def _let_string(self):                # D795
        c = self.get_char()
        sv = self.strvars[letter(c)]
        self.strvar_default_len(sv)
        self.next_char()
        c = self.next_char()
        if c == ord('(') or sv['flags']:
            self.string_var_value(sv)
            self.emit('call $2BF1; push de; push bc')
            self.let_string_value()
            self.emit('pop bc; pop hl; call $2B7F')
            self.set_work = 1
            return
        self.let_string_value()
        self.ld_hl(sv['addr'])
        self.call_rt(RT.STR_ASSIGN)

    # -- DIM (D602) ----------------------------------------------------------------------
    def st_dim(self):
        c = self.get_char()
        k = letter(c)
        if self.next_char() == ord('$'):
            self.next_char()
            ent = self.strvars[k]
            ent['flags'] = 1
            self.dim_sizes(ent)
            fill, t = 0x20, STRING
        else:
            ent = self.arrays[k]
            self.dim_sizes(ent)
            fill, t = 0, ent['type']
        self.t = t
        hl = ent['addr']
        if t == STRING:                                 # D64D: the element length first
            self.emit('ld hl,{}', ent['last'])
            self.st_hl(hl)
            hl += 2
        self.ld_hl(hl)
        size = self.var_size(ent, t)
        self.ld_bc_abs((size - 1) & 0xFFFF)
        self.emit('ld a,{}', fill)
        self.call_rt(RT.MEM_FILL)

    def dim_sizes(self, ent):             # D66B
        self.next_char()
        first = self.number_to_hl()
        if self.get_char() == ord(','):
            self.next_char()
            second = self.number_to_hl()
            self._dim_sizes_set(ent, last=second, first=first)
        else:
            self._dim_sizes_set(ent, last=first, first=0)
        if self.get_char() != ord(')'):
            self.not_supported('DIM')
        self.next_char()

    def _dim_sizes_set(self, ent, last, first):   # D694, D6AE
        """Record an array's sizes the first time it's DIMmed (every pass sees each DIM
        again); a DIM with different sizes is 'Not supported'.  Whether the array was
        DIMmed before is judged by its last dimension alone (0x4526)."""
        seen = ent['last'] != 0
        for key, v in (('last', last), ('first', first)):
            if not seen:
                ent[key] = v
            elif ent[key] != v:
                self.not_supported('DIM again, with different sizes')

    def var_size(self, ent, t):           # D6C7
        n = ent['first'] or 1
        size = (ent['last'] * n) & 0xFFFF
        if t == STRING:
            return size
        if t == REAL:
            return (size * 5) & 0xFFFF
        return (size * 2) & 0xFFFF

    # -- FOR / NEXT (D832, D8ED) ------------------------------------------------------------------
    def st_for(self):
        c = self.get_char()
        f = self.fors[letter(c)]
        if f['flags'] & 0x80:
            self.not_supported('FOR inside FOR with the same variable')
        f['flags'] = 0x80
        addr = self.var_ref()
        f['type'] = self.t
        self.target = self.t
        self.next_char()
        self.expr_to_target()
        self.next_char()
        if self.target != REAL:
            self.st_hl(addr)
            self.emit('push hl')
            self.expr_to_target()
            lim = f['lim']
            self.st_hl(lim)
            if self.get_char() == T_STEP:
                f['flags'] = 0x81
                self.next_char()
                self.expr_integ()
                self.st_hl(lim + 2)
                self.emit('bit 7,h')
            self.emit('pop hl; jp $FFFF')
        else:
            self.ld_de(addr)
            self.call_rt(RT.REAL_COPY_KEEP)
            self.expr_real()
            lim = f['lim']
            self.ld_de(lim)
            self.call_rt(RT.REAL_COPY_KEEP)
            if self.get_char() == T_STEP:
                self.next_char()
                self.expr_real()
            else:
                self.emit('ld hl,1')
                self.call_rt(RT.STACK_POSINT)
            self.ld_de(lim + 5)
            self.call_rt(RT.FOR_REAL_INIT)
            self.emit('jp nz,$FFFF')
        f['body'] = self.pc

    def st_next(self):
        c = self.get_char()
        f = self.fors[letter(c)]
        f['flags'] &= 0x7F
        addr = self.var_ref()
        if self.t == REAL:
            self.ld_de(addr)
            self.ld_hl(f['lim'])
            self.call_rt(RT.NEXT_REAL)
            self.emit_opcode('jp z,nn')                # (its target, the loop body, comes below)
            test = self.pc + 2
        else:
            self.ld_hl_ind(addr)
            lim = f['lim']
            if f['flags']:
                self.ld_de_ind(lim + 2)
                self.emit('add hl,de; bit 7,d')
            else:
                self.emit('inc hl')
            self.st_hl(addr)
            test = self.pc
            self.ld_de_ind(lim)
            if f['flags']:
                self.emit('jr nz,+1')
            self.emit('ex de,hl; and a; sbc hl,de')
            if f['type'] == INTEG:
                self.emit_opcode('jp po,nn')           # past the XOR: no overflow
                self.emit_word_reloc(self.pc + 5)
                self.emit('ld a,h; xor $80; defb $F2')
            else:
                self.emit_opcode('jp nc,nn')           # (the loop body, below)
        body = f['body']
        self.emit_word_reloc(body)
        if self.storing:
            p = (body - 2) & 0xFFFF
            if (self.far[p] | self.far[p + 1] << 8) == 0xFFFF:
                v = (test + self.code_base) & 0xFFFF
                self.far[p] = v & 0xFF
                self.far[p + 1] = v >> 8

    # -- IF (D9B8) -------------------------------------------------------------------------
    def st_if(self):
        self.expr_int()
        self.emit('ld a,h; or l')
        if self.set_work:
            self.emit_call(ROM['SET_WORK'])
            self.set_work = 0
        c = self.next_char()
        st = self.save_state()
        if c in (T_GOTO, T_GOSUB):
            op = 'jp nz,nn' if c == T_GOTO else 'call nz,nn'
            self.next_char()
            computed, hl = self.goto_target()
            if not computed:
                self.emit_goto(op, hl)
                if self.get_char() == CR:
                    return
        self.restore_state(st)
        self.emit('jp z,0')
        self.if_patches.append(self.pc - 2)
        if len(self.if_patches) >= 11:
            self.error(106)
        self.statement()

    # -- GO TO, GO SUB, RESTORE, DATA (DA1F..DB99) ----------------------------------------------
    def goto_target(self):                # DA6D: (computed?, line number or nothing)
        if not self.not_number():
            st = self.save_state()
            self.read_number()
            ok = True
        elif self.get_char() == T_VAL:
            st = self.save_state()
            self.next_char(); self.next_char()
            if self.not_number():
                ok = False
            else:
                x, self.ch = self.fp.dec_to_fp(self.buf, self.ch, self.text_at())
                self.calc.append(x)
                self.next_char()
                ok = True
        else:
            st, ok = None, None
        if ok:
            hl = self.round_pop()
            if self.at_end():
                return False, hl
            self.restore_state(st)
        elif ok is False:
            self.restore_state(st)
        flag = self.restore_directive if self.stmt == T_RESTORE else self.goto_directive
        if not flag:
            self.not_supported('computed line number')
        self.expr_int()
        return True, None

    def emit_goto(self, op, line):        # DA2D (constant target); op: 'jp nn', 'call nz,nn', ...
        addr = self.line_ref(self.check_line(line))
        self.emit_op_reloc(op, addr)

    def st_goto(self):                    # DA1F
        op = 'jp nn' if self.stmt == T_GOTO else 'call nn'
        computed, hl = self.goto_target()
        if computed:
            self.emit_op_reloc(op, self.search_at)       # to the search routine after the library
        else:
            self.emit_goto(op, hl)

    def emit_restore(self, arg=False):    # DA40
        if not arg:
            self.ld_hl(self.data_start)
        else:
            computed, hl = self.goto_target()
            if computed:
                self.emit('set 6,h')
                self.emit_op_reloc('call nn', self.search_at)
                return
            off = self.line_ref(self.check_line(hl) | 0x4000)
            self.ld_hl((off + self.data_start) & 0xFFFF)
        self.emit('ld ($5C6C),hl')

    def st_restore(self):                 # DA3D
        self.emit_restore(arg=not self.at_end())

    def st_data(self):                    # DB08
        bc = self.line_no | 0x4000
        if self.restore_all:
            self.line_ref(bc)
        self.line_store(bc, self.data_size)
        data_int = 0
        if self.get_char() == 0xBA:
            self.next_char()
            data_int = 1
        while not self.at_end():
            where = (self.data_start + self.data_size) & 0xFFFF
            if self.get_char() == ord('"'):
                n = self.data_string(where)
                self.data_size += n + 2
            else:
                self.number_maybe_val()
                if not data_int:
                    if self.storing:
                        self.far[where:where + 5] = self.calc[-1]
                    self.data_size += 5
                else:
                    if self.t == REAL:
                        self.error(102)
                    if self.storing:
                        v = self.round_pop()
                        self.far[where] = v & 0xFF
                        self.far[where + 1] = v >> 8
                    self.data_size += 2
            self.calc = []                                  # SET_STK
            if self.get_char() != ord(','):
                if not self.at_end():
                    self.not_supported('DATA')
                return
            self.next_char()

    def data_string(self, where):         # C54F
        self.get_char()
        i = self.ch
        buf = self.buf
        n = 0
        d = where + 2
        while True:
            i += 1
            if buf[i] == ord('"'):
                i += 1
                if buf[i] != ord('"'):
                    break
            if self.storing:
                self.far[d] = buf[i]
                d += 1
            n += 1
        self.ch = i
        if self.storing:
            self.far[where] = n & 0xFF
            self.far[where + 1] = (n >> 8) & 0xFF
        return n

    # -- the line table (F085; DAB6, DAE9) ---------------------------------------------------------
    # Kept as bytes where the compiler keeps it, in bank 1 on top of the installer's
    # leftover code: (line, address) pairs, ended by a line word with bit 7 set.  A line
    # number of 32768 or more therefore *is* an end marker, and the original then reads
    # whatever follows; to do the same, the table lives in the image's own bytes.
    def line_find(self, bc):              # DAE9: (found, HL)
        mem = self.m.mem
        hl = self.TABLE
        while True:
            e = mem[hl]
            hl += 1
            d = mem[hl]
            if d & 0x80:
                self.line_found = 0
                return False, hl                        # HL at the end marker's high byte
            hl += 1
            if (d << 8 | e) == bc:
                self.line_found = 1
                return True, hl                         # HL at the address field
            hl += 2

    def line_store(self, bc, value):      # DED1 / DB15: store a value in a line's entry, if it has one
        found, hl = self.line_find(bc)
        if found:
            self.m.mem[hl] = value & 0xFF
            self.m.mem[hl + 1] = (value >> 8) & 0xFF

    def check_line(self, n):
        """Fixed: a line number of 16384 or more can't exist in a program (the ROM takes a
        high byte of 0x40 or more as the end of the program), and in the line table bit 6
        means a DATA line and bit 7 the end: GO TO 32768 made the original read past the
        table.  So it's a non-existent line."""
        if not self.exact and n >= 0x4000:
            self.error(104, f'line {n}: line numbers go up to 16383')
        return n

    def line_ref(self, bc):               # DAB6: add (pass 0) or look up a line's address
        found, hl = self.line_find(bc)
        mem = self.m.mem
        if self.pass0:
            if found:
                return hl
            hl -= 1
            mem[hl] = bc & 0xFF
            mem[hl + 1] = (bc >> 8) & 0xFF
            mem[hl + 2] = 0xFF
            mem[hl + 3] = 0xFF
            hl += 5
            mem[hl] |= 0x80
            if hl >= self.TABLE_END:
                self.error(106)
            return hl
        v = mem[hl] | mem[hl + 1] << 8                  # DADD (also when not found: whatever is there)
        if v == 0xFFFF:
            self.error(104, f'line {bc & 0x3FFF}')
        return v

    # =====================================================================================
    # REM and the directives (D27A..D4C9)
    # =====================================================================================
    def st_rem(self):
        if self.get_char() != ord(':'):
            self.end_of_line()
            return
        self.next_char()
        if self.match('OPEN', T_OPEN):
            self.compiling_on = 1
            self.opened = 1
            self.entry_point()
            self.call_rt(RT.STREAM_SCREEN)
            self.emit_restore()
            self.end_of_line()
            return
        if self.match('CLOSE', T_CLOSE):
            if self.compiling_on:
                self.st_stop()
            self.compiling_on = 0
            self.end_of_line()
            return
        if not self.pass0:
            self.end_of_line()
            return
        if self.opened:
            self.error(100)
        self.directive()

    def dir_number(self):                 # D41D
        self.number_from_digits = 1
        v = self.number_to_hl()
        self.number_from_digits = 0
        return v

    def dir_le_number(self):              # D415
        if not self.match('<=', T_LE):
            self.error(100)
        return self.dir_number()

    def directive(self):
        if self.match('LEN', T_LEN):
            while True:
                c = self.get_char()
                if is_alpha(c):
                    sv = self.strvars[letter(c)]
                    self.next_char()
                    if self.get_char() != ord('$'):
                        self.error(100)
                    self.next_char()
                    sv['last'] = self.dir_le_number()
                else:
                    if self.get_char() != ord('$'):
                        self.error(100)
                    self.next_char()
                    v = self.dir_le_number()
                    if v > 0xFF:
                        self.error(100)
                    self.default_len = v
                if self.get_char() != ord(','):
                    self.end_of_line()
                    return
                self.next_char()
        if self.match('USR', T_USR):
            self.code_base = self.dir_number()
            self.auto_base = 0
            self.end_of_line()
            return
        if self.match('INT', 0xBA):
            self.int_directive = 0xFF
            if self.get_char() == ord('+'):
                self.next_char()
                is_fn = self.match('FN', T_FN)
                self.t = POSINT
            else:
                is_fn = self.match('FN', T_FN)
                self.t = INTEG
            if not is_fn:
                self._dir_int_vars()
            else:
                self.get_char()
                self._dir_int_fns()
            return
        if self.match('FN', T_FN):
            if self.get_char() != ord('('):
                self.error(100)
            self.next_char()
            if not self.match('INT', 0xBA):
                self.error(100)
            t = INTEG
            if self.get_char() == ord('+'):
                self.next_char()
                t = POSINT
            self.t = t
            while True:
                c = self.get_char()
                if not is_alpha(c):
                    self.error(100)
                self._set_type(self.fnparams[letter(c)])
                c = self.next_char()
                if c == ord(')'):
                    self.end_of_line()
                    return
                if c != ord(','):
                    self.error(100)
                self.next_char()
        if self.match('LINE', T_LINE):
            self.line_from = self.dir_number()
            self.end_of_line()
            return
        if self.match('LIST', 0xF0):
            self.list_directive = 1
            self.end_of_line()
            return
        if self.match('GOTO', T_GOTO) or self.match('GOSUB', T_GOSUB):
            self.goto_directive = 1
            if self.get_char() == ord(':'):
                self.gosub_all = 1
                self.end_of_line()
                return
            self._dir_line_list(0)
            return
        if self.match('RESTORE', T_RESTORE):
            self.restore_directive = 1
            if self.get_char() == ord(':'):
                self.restore_all = 1
                self.end_of_line()
                return
            self._dir_line_list(0x4000)
            return
        if self.v11:
            if self.match('LPRINT', T_LPRINT):          # v1.1: the report goes to the printer
                self.end_of_line()
                return
            self.error(100)
        if self.match('BREAK', T_REM):
            self.break_check = 1
            self.end_of_line()
            return
        if self.match('VAL', T_VAL):
            self.val_directive = 1
            self.end_of_line()
            return
        self.error(100)

    def _dir_line_list(self, bit):        # D3B2 / D3DB, D4B4
        while True:
            n = self.check_line(self.dir_number()) | bit
            self.line_ref(n)
            if not self.line_found:
                self.n_listed += 1
            if self.get_char() != ord(','):
                self.end_of_line()
                return
            self.next_char()

    def _set_type(self, ent):             # D4A6
        if ent['type']:
            self.error(100)
        ent['type'] = self.t

    def _dir_int_vars(self):              # D430
        while True:
            c = self.get_char()
            if not is_alpha(c):
                self.error(100)
            nxt = self.peek_after()
            if nxt == ord('$'):
                self.error(100)
            if nxt == ord('('):
                self.get_char()
                self._set_type(self.arrays[letter(c)])
                self.next_char(); c = self.next_char()
                if c != ord(')'):
                    self.error(100)
                self.next_char()
            else:
                idx, found, end = self.name_lookup()
                if found:
                    self.error(100)
                self.ch = self.name_add(self.t)
                self.get_char()
            if self.get_char() != ord(','):
                self.end_of_line()
                return
            self.next_char()

    def _dir_int_fns(self):               # D46D
        while True:
            c = self.get_char()
            if not is_alpha(c):
                self.error(100)
            nxt = self.peek_after()
            if nxt in (ord('$'), ord('(')):
                self.error(100)
            fe = self.fn_entry()
            self._set_type(fe)
            if self.get_char() != ord(','):
                self.end_of_line()
                return
            self.next_char()

    def entry_point(self):                # DF3E: 'LINE n: address' (passes 1 and 2)
        if self.pass0:
            return
        if self.counting:
            self.printed1.append((self.line_no, self.pc))
        if not self.counting:
            self.entries.append((self.line_no, (self.pc + self.code_base) & 0xFFFF))
            self.printed.append((self.line_no, (self.pc + self.code_base) & 0xFFFF))

    # =====================================================================================
    # lines and passes (DDCD, DE6E, DF10, DF89)
    # =====================================================================================
    STATEMENTS = None

    def statement(self):                  # DDCD
        if self.break_check:
            self.call_rt(RT.BREAK_CHECK)
        if self.set_work:
            self.emit_call(ROM['SET_WORK'])
            self.set_work = 0
        c = self.get_char()
        self.stmt = c
        self.next_char()
        if c == ord(':'):
            return
        if c == CR:
            self.end_of_line()
            return
        if c == T_PLAY and not self.v11:
            self.st_play()
            return
        if c < T_DEFFN:
            self.not_supported(f'statement {c:#x}')
        h = self.dispatch.get(c)
        if h is None:
            self.not_supported(f'statement {c:#x}')
        h()

    def load_line(self):                  # DF10
        self.if_patches = []
        if self.li >= len(self.lines):
            return False
        n, body = self.lines[self.li]
        self.line_no = n
        if self.v11:
            off = self.line_offsets[self.li] + 4
            self.buf = self.prog[off:] + bytearray(b'\x0d' * 8)
        else:
            if len(body) > 1024:
                self.error(106)
            self.linebuf[0:len(body)] = body
            self.buf = self.linebuf
        self.ch = 0
        return True

    def end_of_line(self):                # DE6E
        if self.storing:
            v = (self.pc + self.code_base) & 0xFFFF
            for p in self.if_patches:
                self.far[p] = v & 0xFF
                self.far[p + 1] = v >> 8
        else:
            # DE73: would the code, built in place below RAMTOP, reach this BASIC line?
            # (F077, the line's address, + 44E9, which is free space - PROG)
            if self.pc > (self.prog_addr + self.line_offsets[self.li] + self.free_below) & 0xFFFF:
                self.overflow = 1
        self.li += 1
        if not self.load_line():
            return
        if not self.counting:
            self.line_starts.append((self.line_no, self.pc))
        if not self.compiling_on:
            return
        if self.gosub_all:
            self.line_ref(self.line_no)
        self.line_store(self.line_no, self.pc)
        if self.line_no >= self.line_from:
            self.entry_point_line()

    def entry_point_line(self):
        if not self.pass0 and self.counting:
            self.printed1.append((self.line_no, self.pc))
        if not self.pass0 and not self.counting:
            self.line_addrs.append((self.line_no, (self.pc + self.code_base) & 0xFFFF))
            self.printed.append((self.line_no, (self.pc + self.code_base) & 0xFFFF))

    def run_pass(self):                   # DF89
        self.compiling_on = 0
        self.number_from_digits = 0
        self.set_work = 0
        self.probing = 0
        self.pc = 0
        self.data_size = 0
        self.li = 0
        self.calc = []
        self.load_line()
        while self.li < len(self.lines):
            if self.compiling_on:
                self.statement()
            elif self.get_char() == T_REM:
                self.next_char()
                self.st_rem()
            else:
                self.end_of_line()
        if self.compiling_on:
            self.st_stop()
        self.pc = self.m.layout(self.pc, self.counting, self.code_base)
        if self.restore_directive or self.goto_directive:
            self.emit_line_table()

    SEARCH = ('ld e,(hl); inc hl; ld d,(hl); bit 7,d; jr nz,+25; inc hl; ex de,hl; and a; sbc hl,bc; '
              'ex de,hl; jr z,+4; inc hl; inc hl; jr -19; ld e,(hl); inc hl; ld d,(hl); ex de,hl; '
              'bit 6,b; jr nz,+1; jp (hl); ld ($5C6C),hl; ret; ld ($5C45),bc; rst 8; defb $16')

    def emit_line_table(self):            # DFD7: the search routine, then (line, address) pairs
        self.search_at = self.pc
        self.emit('ld b,h; ld c,l')
        self.ld_hl(self.search_at + 43)
        self.emit(self.SEARCH)
        bc = self.n_listed
        mem = self.m.mem
        hl = self.TABLE
        while True:                                      # E01E
            line = mem[hl] | mem[hl + 1] << 8
            hl += 2
            if line & 0x8000:
                break
            if bc:
                bc -= 1
            else:
                flag = self.restore_all if line & 0x4000 else self.gosub_all
                if not flag:
                    hl += 2
                    continue
            self.emit_word(line)
            addr = mem[hl] | mem[hl + 1] << 8
            hl += 2
            if line & 0x4000:
                addr = (addr + self.data_start) & 0xFFFF
            self.emit_word_reloc(addr)
        self.emit_word(0xFFFF)                           # the table's end (data)

    def layout_vars(self):                # E5D6
        pc = self.pc + 2 * (self.n_int & 0xFF) + 5 * (self.n_real & 0xFF)
        for f in self.fors:                                  # E616
            if f['type'] != 0xFF:
                f['lim'] = pc
                pc += 4 if f['type'] != REAL else 10
        for a in self.arrays:                                # E5F4
            a['addr'] = pc
            pc += self.var_size(a, a['type'])
        for s in self.strvars:                               # E605
            s['addr'] = pc
            n = self.var_size(s, STRING)
            pc += n + 2 if n else 0
        self.pc = pc & 0xFFFF

    # =====================================================================================
    # the driver (E3AA)
    # =====================================================================================
    def reset(self, prog):
        from_lines = []
        p = 0
        offs = []
        while p + 4 <= len(prog):
            n = prog[p] << 8 | prog[p + 1]
            ln = prog[p + 2] | prog[p + 3] << 8
            offs.append(p)
            from_lines.append((n, bytes(prog[p + 4:p + 4 + ln])))
            p += 4 + ln
        self.lines = from_lines
        self.line_offsets = offs + [p]
        self.prog = bytearray(prog)
        self.linebuf = bytearray(1024 + 16)             # 45A9, zeroed by the CLS at the start
        self.linebuf[-1] = CR                           # (a stop for NEXT_CHAR past a line's end)
        self.far[:] = bytes(65536)
        self.m.clear_table()
        self.auto_base = 1                 # 451F
        self.default_len = 0xFF            # 453F
        self.line_from = 0xFFFF            # 4515
        self.code_base = 0                 # 4517
        self.fors = [dict(type=0xFF, flags=0, lim=0, body=0) for _ in range(26)]
        self.strfns = [dict(type=STRING, ptypes=0, addr=0) for _ in range(26)]
        self.numfns = [dict(type=REAL, ptypes=0, addr=0) for _ in range(26)]
        self.fnparams = [dict(type=0, num=0xFFFF, str=0xFFFF) for _ in range(26)]
        self.strvars = [dict(flags=0, addr=0, last=0, first=0) for _ in range(26)]
        self.arrays = [dict(type=0, addr=0, last=0, first=0) for _ in range(26)]
        self.names = []
        self.name_bytes = 0
        self.n_int = self.n_real = 0
        # a fresh machine: bank 1 as the tape left it (the image), zeros beyond it
        img = self.m.img
        self.m.mem[img.org:img.org + len(img.data)] = img.data
        if self.v11:
            self.m.mem[0x4541:0x5800] = bytes(0x5800 - 0x4541)
        else:
            self.m.mem[img.org + len(img.data):0x10000] = bytes(0x10000 - img.org - len(img.data))
        self.m.mem[self.TABLE + 1] = 0x80               # E3EE: an empty table
        self.n_listed = 0                  # 4519
        self.vars_start = 0                # F07B
        self.data_start = 0                # 44F1
        self.search_at = 0                 # 44F9
        self.int_directive = 0             # 4532
        self.goto_directive = self.restore_directive = 0    # 4534, 4533
        self.gosub_all = self.restore_all = 0               # 4535, 4536
        self.break_check = self.val_directive = 0           # 4537, 4543
        self.list_directive = 0            # 4522
        self.opened = 0                    # 452D
        self.overflow = 0                  # 4521
        self.input_flag = 0                # 4544
        self.probe_simple = self.probe_pow2 = 0
        self.const_index = 0
        self.colours = self.stream_used = self.sep = 0
        self.t = REAL
        self.target = REAL
        self.stmt = 0
        self.entries = []
        self.line_addrs = []
        self.line_starts = []
        self.printed = []
        self.printed1 = []
        self.unwritten = []
        self.found = 0
        self.line_found = 0

    @property
    def dispatch(self):
        if self.STATEMENTS is None:
            self.STATEMENTS = {
                T_DEFFN: self.st_deffn, T_OPEN: self.st_open, T_CLOSE: self.st_close, 0xD7: self.st_beep,
                0xD8: self.st_circle, 0xD9: self.st_colour, 0xDA: self.st_colour, 0xDB: self.st_colour,
                0xDC: self.st_colour, 0xDD: self.st_colour, 0xDE: self.st_colour, 0xDF: self.st_out,
                T_LPRINT: self.st_print, T_STOP: self.st_stop, T_READ: self.st_read, T_DATA: self.st_data,
                T_RESTORE: self.st_restore, 0xE7: self.st_border, 0xE9: self.st_dim, T_REM: self.st_rem,
                T_FOR: self.st_for, T_GOTO: self.st_goto, T_GOSUB: self.st_goto, T_INPUT: self.st_input,
                T_LET: self.st_let, 0xF2: self.st_pause, 0xF3: self.st_next, 0xF4: self.st_poke,
                T_PRINT: self.st_print, 0xF6: self.st_plot, 0xF9: self.st_randomize, 0xFA: self.st_if,
                0xFB: self.st_cls, 0xFC: self.st_draw, 0xFE: self.st_return, 0xFF: self.st_copy,
            }
        return self.STATEMENTS

    def compile(self, prog):
        res = Result()
        try:
            self._compile(prog, res)
            res.ok = True
        except CompileError as e:
            res.ok = False
            res.error = self.message(e.code)
            res.error_line = e.line
            res.detail = e.detail
            res.rom_report = isinstance(e.code, tuple)
        except romfp.ROMError as e:
            # any other ROM error while compiling (e.g. 'Number too big' from VAL "1e99"):
            # the original has no handler for it either
            res.ok = False
            res.error = self.message(('rom', e.code, NOTE_NO_HANDLER if self.exact else ''))
            res.error_line = self.line_no
            res.rom_report = True
        return res

    def message(self, code):
        """A message's text: the compiler's own (from the image), or a ROM report's as
        the ROM prints it, 'B Integer out of range' (from the ROM), plus pyhsb's note."""
        import report
        if isinstance(code, tuple):
            _, n, note = code
            n += 1
            letter = str(n) if n < 10 else chr(ord('A') + n - 10)
            return f'{letter} ' + report.po_msg(self.rom, ROM_REPORTS, n).decode('latin-1') + note
        return report.po_msg(self.m.img, MSG_TABLE[self.v11], code - 100).decode('latin-1')

    def _compile(self, prog, res):
        self.reset(prog)
        top = self.ramtop + 1                              # 44E7
        vars_addr = self.prog_addr + len(prog)             # VARS
        free = top - vars_addr
        if free < 300:
            raise CompileError(108)
        self.free300 = free - 300                          # 450F
        self.free_below = (free - self.prog_addr) & 0xFFFF  # 44E9, as the compiler has it
        # pass 0: directives, variables, the line table
        self.pass0 = 1
        self.counting = 1
        self.line_no = None
        self.run_pass()
        self.m.clear_table()
        self.pass0 = 0
        # pass 1: sizes and the routine layout
        self.run_pass()
        self.data_start = self.pc                          # 44F1
        self.pc = (self.pc + self.data_size) & 0xFFFF
        self.vars_start = self.pc                          # F07B
        self.layout_vars()
        self.var_bytes = (self.pc - self.vars_start) & 0xFFFF   # F07D
        total = self.pc
        fits = self.free300 >= total
        size = total if fits else self.vars_start          # 4511
        if total + 0x6000 > 0xFFFF or total + 0x6000 > top:
            raise CompileError(108)
        if self.free300 + len(prog) < self.data_start:
            raise CompileError(108)
        if self.overflow:
            raise CompileError(108)
        if self.data_size and self.free300 < self.vars_start:
            raise CompileError(107)
        self.out_base = top - size                         # F07F
        if self.auto_base:
            self.code_base = (top - total) & 0xFFFF
        if self.code_base + total > top:
            raise CompileError(109)
        if not fits:
            # the original asks whether to delete the BASIC program to make room, and then
            # moves the code; pyhsb doesn't do that
            raise CompileError(108, detail='the original would offer to delete the BASIC program '
                                           'to make room; pyhsb does not do that')
        # pass 2: the code.  The compiler writes over what is in RAM; the few bytes it
        # skips (DEF FN parameters) keep what was there.  On a freshly set-up 128 that is
        # the compiler's own image, which the Tape Loader left at 48900..62122 before
        # installing it into the RAM disk; elsewhere, zeros (the rest is stack residue
        # that the tape can't tell us).
        img = self.m.img
        for i in range(self.vars_start):
            self.far[i] = img.prior_ram((self.out_base + i) & 0xFFFF) if self.exact else 0
        self.counting = 0
        self.run_pass()
        res.code = bytes(self.far[0:self.vars_start])
        res.v11 = self.v11
        res.load = self.code_base
        res.save = self.out_base
        res.var_bytes = self.var_bytes
        res.basic_bytes = len(prog)
        res.entries = list(self.entries)
        res.unwritten = list(self.unwritten)
        res.rts = [(n, (self.m.rt_addr(n) + self.code_base) & 0xFFFF) for n in range(1, 132) if self.m.used(n)]
        res.variables = self.variable_list()
        res.line_starts = list(self.line_starts)
        res.printed = list(self.printed)
        res.printed1 = list(self.printed1)
        res.list_directive = self.list_directive
        res.arrays = [dict(a) for a in self.arrays]
        res.strvars = [dict(v) for v in self.strvars]

    def variable_list(self):
        out = []
        for idx, (name, typ) in enumerate(self.names):
            t = typ & 0x7F
            off = 2 * idx if idx < self.n_int else 5 * (idx - self.n_int) + 2 * self.n_int
            out.append((name, t, (off + self.vars_start + self.code_base) & 0xFFFF))
        return out
