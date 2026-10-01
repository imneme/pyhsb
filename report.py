"""The compiler's printed report, byte for byte (v1.2, output to the printer:
the P command, which is how hisoft.py drives it).

What the compiler sends through RST 10 (raw: tokens stay tokens):
  - each entry point and each REM : LINE line, in pass 1 ('LINE n: +offset')
    and in pass 2 ('LINE n: address #HEX');
  - with REM : LIST, every routine used and every variable, array and string;
  - the summary (M/C bytes, variables, BASIC) and the SAVE / LOAD lines, with a
    flashing D or E in front for one half of a big program.

Fields are positioned by 0xE76A, meant to be TAB column.  Its printer branch
sends TAB, 0, *row* (7), so the printer gets TAB 1792: column 0 on a
32-column printer, every field on its own line.  exact=True reproduces that;
otherwise each field gets its column (0, 9, 12 or 21, as on the screen).

All the words come from the user's image (PO_MSG tables at 0xE23F, the
summary, and 0xC3AE, the type names); numbers are the ROM's PRINT_FP of an
integer, which is plain decimal.
"""

SUMMARY_TABLE = 0xE23F     # v1.2: 'HISOFT BASIC 1.2 / (c) ...', 'M/C: ', ' BYTES...', ...
TYPE_TABLE = 0xC3AE        # v1.2: REAL, INTEG, POSINT, ..., STR
LINE_TOKEN = 0xCA
STR_TYPE = 4               # the type table's entry for strings (0x80 is shown as 4)


def po_msg(src, table, n):
    """The ROM's PO_MSG: message n of a table that starts with a byte with bit 7
    set, each message ending in a character with bit 7 set.  src: an Image
    (hbcimage) or the ROM's bytes."""
    byte = src.byte if hasattr(src, 'byte') else src.__getitem__
    a = table
    k = n + 1
    while True:
        b = byte(a)
        a += 1
        if b & 0x80:
            k -= 1
            if k == 0:
                break
    out = bytearray()
    while True:
        b = byte(a)
        a += 1
        out.append(b & 0x7F)
        if b & 0x80:
            return bytes(out)


def num(n):
    return str(n & 0xFFFF).encode()


def addr(n):                                   # E7B4: decimal, ' #', four hex digits
    n &= 0xFFFF
    return num(n) + b' #' + f'{n:04X}'.encode()


def dims(ent):                                 # E7E6: (first,last) or (last)
    s = b'('
    if ent['first']:
        s += num(ent['first']) + b','
    return s + num(ent['last']) + b')'


def render(img, res, exact=False):
    if res.parts:                              # a big program's two halves: both reports, D's first
        return b''.join(render(img, part, exact) for part in res.parts)
    def tab(col):                              # E76A with B = 7, C = col
        return b'\x17\x00\x07' if exact else bytes([0x17, col, 0])

    def entry(line, value, pass1):             # DF3E
        return (tab(0) + bytes([LINE_TOKEN]) + num(line) + b': '
                + (b'+' + num(value) if pass1 else addr(value)) + b'\r')

    def typename(t):
        return po_msg(img, TYPE_TABLE, t)

    out = bytearray()
    for line, rel in res.printed1:
        out += entry(line, rel, True)
    for line, a in res.printed:
        out += entry(line, a, False)
    if res.list_directive:
        out += b'\r'                                             # E66A: E6C8 first
        for n, a in res.rts:                                     # E66D: RTn and its address
            out += tab(0) + b'RT' + num(n) + tab(9) + addr(a) + b'\r'
        for name, typ, a in res.variables:                       # E6D8: the name table, dotted to 11
            nm = name.encode()[:11].ljust(11, b'.')
            out += tab(0) + nm + tab(12) + typename(typ) + tab(21) + addr(a) + b'\r'
        for k, ent in enumerate(res.arrays):                     # E702: arrays a..z
            if ent['last']:
                out += (tab(0) + bytes([0x61 + k]) + dims(ent) + tab(12) + typename(ent['type'])
                        + tab(21) + addr(ent['addr'] + res.load) + b'\r')
        for k, ent in enumerate(res.strvars):                    # E731: strings a..z
            if ent['last']:
                out += tab(0) + bytes([0x61 + k]) + b'$'
                if ent['flags']:                                 # DIMmed: its size by the name
                    out += dims(ent)
                out += tab(12) + typename(STR_TYPE)
                if not ent['flags']:                             # otherwise its maximum length
                    out += dims(ent)
                out += tab(21) + addr(ent['addr'] + res.load) + b'\r'
        out += tab(0) + b'\r'                                    # the last E6D8 finds nothing
    m = lambda n: po_msg(img, SUMMARY_TABLE, n)                  # E1DC, E209
    mc = res.mc_bytes or len(res.code)                           # the whole program's code + DATA
    out += m(0) + m(1) + num(mc) + m(2) + num(res.var_bytes) + m(3) + num(res.basic_bytes) + m(4)
    out += {'D': m(8), 'E': m(9)}.get(res.mode, b'')             # a flashing D or E: which half this is
    out += m(5) + num(res.save) + b',' + num(len(res.code)) + b'\r' + m(6) + num(res.load)
    return bytes(out)


def render_text(data, kw):
    """The printer bytes as text: 0x0D is a new line, tokens are spelled out,
    0x7F is ©.  TAB (0x17 + two bytes) becomes padding to the next multiple of 8,
    so the TAB 1792 bug (every field at column 0 on a real printer) reads as columns."""
    out, line, col, i = [], [], 0, 0
    while i < len(data):
        b = data[i]
        if b == 0x0D:
            out.append(''.join(line)); line = []; col = 0
        elif b == 0x17 and i + 2 < len(data):
            to = data[i + 1] | data[i + 2] << 8
            if to < 32:                              # a real TAB column
                if col > to:
                    out.append(''.join(line)); line = []; col = 0
                line.append(' ' * (to - col)); col = to
            elif col:                                # the TAB 1792 bug: every field at column 0
                pad = 8 - col % 8                    # on a printer; shown here as 8-column stops
                line.append(' ' * pad); col += pad
            i += 2
        elif b == 0x16 and i + 2 < len(data):
            i += 2
        elif 0x10 <= b <= 0x15 and i + 1 < len(data):  # INK .. OVER (the D or E flashes)
            i += 1
        elif b == 0x06:
            pad = 16 - col % 16
            line.append(' ' * pad); col += pad
        elif b in kw.TOKEN:
            w = kw.TOKEN[b] + ' '
            line.append(w); col += len(w)
        elif b == 0x7F:
            line.append('©'); col += 1
        elif b == 0x60:
            line.append('£'); col += 1
        elif 0x20 <= b < 0x80:
            line.append(chr(b)); col += 1
        else:
            line.append('{%02x}' % b); col += 1
        i += 1
    out.append(''.join(line))
    return '\n'.join(out)
