"""A tiny Z80 assembler for the code generator's fragments, so they read as
instructions rather than hex:

    asm('ld hl,$2758; exx; ret')           -> bytes
    asm('jp z,{}', 0)                      -> {} takes a value (a number)

Covers the instructions pyhsb emits; anything else raises.  Numbers are
decimal, $hex or 0xhex; relative jumps take an offset ('jr nz,+1'), not a
label.  Encodings are Zilog's.
"""
import functools
import re

R8 = {'b': 0, 'c': 1, 'd': 2, 'e': 3, 'h': 4, 'l': 5, '(hl)': 6, 'a': 7}
RP = {'bc': 0, 'de': 1, 'hl': 2, 'sp': 3}
RP2 = {'bc': 0, 'de': 1, 'hl': 2, 'af': 3}
CC = {'nz': 0, 'z': 1, 'nc': 2, 'c': 3, 'po': 4, 'pe': 5, 'p': 6, 'm': 7}
ALU = {'add': 0, 'adc': 1, 'sub': 2, 'sbc': 3, 'and': 4, 'xor': 5, 'or': 6, 'cp': 7}
ROT = {'rlc': 0, 'rrc': 1, 'rl': 2, 'rr': 3, 'sla': 4, 'sra': 5, 'sll': 6, 'srl': 7}
PLAIN = {'nop': [0x00], 'rlca': [0x07], 'rrca': [0x0F], 'rla': [0x17], 'rra': [0x1F], 'daa': [0x27],
         'cpl': [0x2F], 'scf': [0x37], 'ccf': [0x3F], 'halt': [0x76], 'exx': [0xD9], 'di': [0xF3],
         'ei': [0xFB], 'neg': [0xED, 0x44], 'ret': [0xC9], 'ldir': [0xED, 0xB0], 'lddr': [0xED, 0xB8],
         'ex de,hl': [0xEB], 'ex (sp),hl': [0xE3], "ex af,af'": [0x08], 'ld sp,hl': [0xF9],
         'jp (hl)': [0xE9], 'reti': [0xED, 0x4D]}


def num(s):
    s = s.strip()
    neg = s.startswith('-')
    if neg or s.startswith('+'):
        s = s[1:]
    if s.startswith('$'):
        v = int(s[1:], 16)
    elif s.lower().startswith('0x'):
        v = int(s, 16)
    else:
        v = int(s)
    return -v if neg else v


def w(v):
    v &= 0xFFFF
    return [v & 0xFF, v >> 8]


def b(v):
    if not -128 <= v <= 255:
        raise ValueError(f'byte out of range: {v}')
    return [v & 0xFF]


def one(ins):
    ins = re.sub(r'\s+', ' ', ins.strip().lower())
    ins = re.sub(r'\s*,\s*', ',', ins)
    if ins in PLAIN:
        return list(PLAIN[ins])
    op, _, args = ins.partition(' ')
    a = args.split(',') if args else []
    if op == 'defb':
        return [num(x) & 0xFF for x in a]
    if op == 'defw':
        return sum((w(num(x)) for x in a), [])
    if op == 'ld':
        d, s = a
        if d in R8 and s in R8:
            return [0x40 | R8[d] << 3 | R8[s]]
        if d in R8 and s not in R8 and not s.startswith('('):
            return [0x06 | R8[d] << 3] + b(num(s))
        if d in RP and not s.startswith('('):
            return [0x01 | RP[d] << 4] + w(num(s))
        if d == 'hl' and s.startswith('('):
            return [0x2A] + w(num(s[1:-1]))
        if s == 'hl' and d.startswith('('):
            return [0x22] + w(num(d[1:-1]))
        if d == 'a' and s in ('(bc)', '(de)'):
            return [0x0A if s == '(bc)' else 0x1A]
        if s == 'a' and d in ('(bc)', '(de)'):
            return [0x02 if d == '(bc)' else 0x12]
        if d == 'a' and s.startswith('('):
            return [0x3A] + w(num(s[1:-1]))
        if s == 'a' and d.startswith('('):
            return [0x32] + w(num(d[1:-1]))
        if d in RP and s.startswith('('):
            return [0xED, 0x4B | RP[d] << 4] + w(num(s[1:-1]))
        if s in RP and d.startswith('('):
            return [0xED, 0x43 | RP[s] << 4] + w(num(d[1:-1]))
    if op in ('push', 'pop'):
        return [(0xC5 if op == 'push' else 0xC1) | RP2[a[0]] << 4]
    if op in ('inc', 'dec'):
        r = a[0]
        if r in R8:
            return [(0x04 if op == 'inc' else 0x05) | R8[r] << 3]
        return [(0x03 if op == 'inc' else 0x0B) | RP[r] << 4]
    if op == 'add' and len(a) == 2 and a[0] == 'hl':
        return [0x09 | RP[a[1]] << 4]
    if op in ('adc', 'sbc') and len(a) == 2 and a[0] == 'hl':
        return [0xED, (0x4A if op == 'adc' else 0x42) | RP[a[1]] << 4]
    if op in ALU:
        s = a[-1]
        if len(a) == 2 and a[0] != 'a':
            raise ValueError(ins)
        if s in R8:
            return [0x80 | ALU[op] << 3 | R8[s]]
        return [0xC6 | ALU[op] << 3] + b(num(s))
    if op in ROT:
        return [0xCB, ROT[op] << 3 | R8[a[0]]]
    if op in ('bit', 'res', 'set'):
        base = {'bit': 0x40, 'res': 0x80, 'set': 0xC0}[op]
        return [0xCB, base | num(a[0]) << 3 | R8[a[1]]]
    if op in ('jp', 'call'):
        if len(a) == 1:
            return [0xC3 if op == 'jp' else 0xCD] + w(num(a[0]))
        return [(0xC2 if op == 'jp' else 0xC4) | CC[a[0]] << 3] + w(num(a[1]))
    if op in ('jr', 'djnz'):
        d = num(a[-1])
        if not -128 <= d <= 127:
            raise ValueError(f'relative jump out of range: {ins!r}')
        if op == 'djnz':
            return [0x10] + b(d)
        if len(a) == 1:
            return [0x18] + b(d)
        return [0x20 | CC[a[0]] << 3] + b(d)
    if op == 'ret':
        return [0xC0 | CC[a[0]] << 3]
    if op == 'rst':
        return [0xC7 | num(a[0])]
    if op == 'out' and a[0] == '(c)':
        return [0xED, 0x41 | R8[a[1]] << 3]
    if op == 'in' and a[1] == '(c)':
        return [0xED, 0x40 | R8[a[0]] << 3]
    raise ValueError(f'z80asm: cannot assemble {ins!r}')


@functools.lru_cache(maxsize=None)
def _asm(text):
    out = []
    for ins in text.split(';'):
        if ins.strip():
            out += one(ins)
    return bytes(out)


def asm(text, *vals):
    if vals:
        text = text.format(*vals)
    return _asm(text)
