"""BASIC source in, program bytes out, stored the way the ROM stores a line.

    kw = Keywords(rom)                         # the ROM's own keyword table (0x0095), plus the 128's PLAY
    prog = tokenize('10 PRINT BIN 101\\n', kw, fp)
    name, prog = read_program('prog.bas', kw, fp)      # .bas (speccy-basic if installed) or .tap
    prog = add_directives(prog, ['INT a,b'], open_=True, lines=['271 REM : CLOSE #'], kw=kw)

A stored line: keywords are tokens; each number is followed by 0x0E and the
5-byte value the ROM's DEC_TO_FP gives (BIN too); each DEF FN parameter is
followed by 0x0E and five zero bytes; REMs and strings are kept as typed.
"""
import re
from pathlib import Path

import tap

T_BIN, T_REM, T_DEFFN = 0xC4, 0xEA, 0xCE


class SourceError(Exception):
    """A program that can't be read (a parse error from speccy-basic, no free line for
    a directive, a character the Spectrum doesn't have...)."""
ALIASES = {'GOTO': 'GO TO', 'GOSUB': 'GO SUB', 'OPEN#': 'OPEN #', 'CLOSE#': 'CLOSE #',
           'DEFFN': 'DEF FN', 'RANDOMISE': 'RANDOMIZE'}


class Keywords:
    """The keyword table, read from the ROM: TOKEN[code] -> 'PRINT', CODE_FOR['PRINT'] -> code."""

    def __init__(self, rom):
        toks, cur, a = [], '', 0x0095                   # the ROM's TKN_TABLE: '?', then RND .. COPY
        while len(toks) < 92:
            c = rom[a]
            a += 1
            cur += chr(c & 0x7F)
            if c & 0x80:
                toks.append(cur.strip())
                cur = ''
        self.TOKEN = {0xA5 + i: t for i, t in enumerate(toks[1:])}
        self.TOKEN[0xA3] = 'SPECTRUM'                    # the 128's two new keywords
        self.TOKEN[0xA4] = 'PLAY'
        self.CODE_FOR = {t: c for c, t in self.TOKEN.items()}
        self.spell = dict(self.CODE_FOR)
        for alias, word in ALIASES.items():
            self.spell[alias] = self.CODE_FOR[word]
        self.words = sorted(self.spell, key=len, reverse=True)

    def detokenize(self, data):
        """Line bytes -> text, keywords spelled out (for listings)."""
        out = []
        for b in data:
            if b in self.TOKEN:
                w = self.TOKEN[b]
                out.append(w + ' ')
            elif b == 0x0D:
                break
            elif 0x20 <= b < 0x80:
                out.append({0x60: '£', 0x7F: '©'}.get(b, chr(b)))
            else:
                out.append(f'{{{b:02x}}}')
        return ''.join(out)


def _char(ch):
    if ch == '£':
        return 0x60
    if ch == '©':
        return 0x7F
    o = ord(ch)
    if o >= 128:
        raise SourceError(f'no Spectrum character for {ch!r}')
    return o


def tokenize_line(text, kw):
    """A line's text (without its number) -> codes: keywords (upper case) become
    tokens, nothing inside quotes or after REM does, and spaces next to keywords
    are dropped (the ROM draws its own)."""
    def boundary_ok(s, i, w):
        if w[0].isalpha() and i > 0 and (s[i - 1].isalnum() or s[i - 1] == '$'):
            return False
        j = i + len(w)
        if w[-1].isalpha() and j < len(s) and (s[j].isalnum() or s[j] == '$'):
            return False
        return True

    out = []
    i, n = 0, len(text)
    in_quotes = rem = False
    last_was_token = False
    while i < n:
        c = text[i]
        if rem or in_quotes:
            if c == '"' and not rem:
                in_quotes = False
            out.append(_char(c))
            i += 1
            continue
        if c == ' ':
            j = i
            while j < n and text[j] == ' ':
                j += 1
            nxt_is_kw = any(text.startswith(w, j) and boundary_ok(text, j, w) for w in kw.words)
            if not (last_was_token or nxt_is_kw) and j < n:
                out.extend([0x20] * (j - i))
            i = j
            continue
        if c == '"':
            in_quotes = True
            out.append(0x22)
            last_was_token = False
            i += 1
            continue
        for w in kw.words:
            if text.startswith(w, i) and boundary_ok(text, i, w):
                code = kw.spell[w]
                out.append(code)
                i += len(w)
                last_was_token = True
                if code == T_REM:
                    rem = True
                    if i < n and text[i] == ' ':        # the one space after REM is the ROM's
                        i += 1
                break
        else:
            out.append(_char(c))
            last_was_token = False
            i += 1
    return bytes(out)


def _is_ident(c):
    return 0x41 <= c <= 0x5A or 0x61 <= c <= 0x7A or 0x30 <= c <= 0x39


def hide_numbers(body, fp):
    """Insert 0x0E + the ROM's 5-byte value after each number (not in strings, REMs or
    names), and 0x0E + five zeros after each DEF FN parameter.  fp: a romfp.ROMFP."""
    out = bytearray()
    i, n = 0, len(body)
    in_str = False
    prev = 0
    while i < n:
        c = body[i]
        if in_str:
            out.append(c)
            if c == 0x22:
                in_str = False
            i += 1
            continue
        if c == 0x22:
            in_str = True
            out.append(c)
            i += 1
            prev = c
            continue
        if c == T_REM:
            out += body[i:]
            break
        starts = (0x30 <= c <= 0x39) or (c == 0x2E and i + 1 < n and 0x30 <= body[i + 1] <= 0x39) or c == T_BIN
        if starts and not _is_ident(prev):
            x, end = fp.dec_to_fp(bytes(body) + b'\x0d', i)
            out += body[i:end] + b'\x0e' + x
            i = end
            prev = 0x30
            continue
        if c == T_DEFFN:                                  # DEF FN f[$] ( p[$] <0E 00 00 00 00 00> , ... )
            out.append(c)
            i += 1
            while i < n and body[i] != 0x28:
                out.append(body[i])
                i += 1
            if i < n:
                out.append(body[i])
                i += 1
            while i < n and body[i] != 0x29:
                if _is_ident(body[i]):
                    out.append(body[i])
                    i += 1
                    if i < n and body[i] == 0x24:
                        out.append(body[i])
                        i += 1
                    out += b'\x0e\x00\x00\x00\x00\x00'
                else:
                    out.append(body[i])
                    i += 1
            prev = 0
            continue
        out.append(c)
        prev = c
        i += 1
    return bytes(out)


def tokenize(text, kw, fp):
    """Plain numbered BASIC text -> program bytes."""
    lines = []
    for k, line in enumerate(text.split('\n'), 1):
        line = line.strip()
        if not line:
            continue
        num, _, rest = line.partition(' ')
        if not num.isdigit():
            raise SourceError(f'line {k} has no line number ({line[:30]!r}): without spectrum-basic '
                              f'installed, pyhsb reads plain numbered BASIC; for unnumbered lines, labels '
                              f'or the enhanced syntax, install it (pip install spectrum-basic)')
        lines.append((int(num), hide_numbers(tokenize_line(rest, kw), fp) + b'\x0d'))
    return tap.join_lines(lines)


def read_program(path, kw, fp):
    """(name, program bytes) from a .tap (its first BASIC program) or a .bas.  A .bas
    goes through speccy-basic when it's installed (it knows labels and the enhanced
    syntax); otherwise it must be plain numbered BASIC."""
    path = Path(path).expanduser()
    if path.suffix.lower() == '.tap':
        return tap.program_of_tap(path.read_bytes())
    try:
        import spectrum_basic as sb
        from spectrum_basic.core import eliminate_control_lines
    except ImportError:
        return path.stem[:10], tokenize(path.read_text(), kw, fp)
    try:
        prog = sb.parse_file(str(path))
        eliminate_control_lines(prog)
        sb.number_lines(prog, remove_labels=True)
        return path.stem[:10], bytes(prog)
    except Exception as e:                  # textX syntax errors and speccy-basic's own
        raise SourceError(f'{path.name}: speccy-basic could not read it: {str(e).splitlines()[0]}') from e


# -- directives -------------------------------------------------------------------------

def _skip_codes(body):
    """What GET_CHAR skips at the start of a line: spaces, INK..OVER + 1, AT/TAB + 2."""
    i = 0
    while i < len(body) and (body[i] == 0x20 or 0x10 <= body[i] <= 0x17):
        i += 1 if body[i] == 0x20 else (2 if body[i] < 0x16 else 3)
    return body[i:]


def open_lines(prog):
    """Line numbers holding REM : OPEN # (token 0xD3 or spelled out)."""
    out = []
    for n, body in tap.split_lines(prog):
        body = _skip_codes(body)
        if body[:1] == bytes([T_REM]):
            rest = body[1:].replace(b' ', b'')
            if rest.startswith(b':\xd3') or rest.upper().startswith(b':OPEN#'):
                out.append(n)
    return out


def directive_line(text, kw):
    """'REM : INT a,b' -> the line's body, with the directive's keywords as tokens
    (the way the tape's examples store them; v1.2 also reads them spelled out)."""
    m = re.match(r'\s*REM\s*:\s*(.*)$', text)
    if not m:
        raise ValueError(f'not a REM : directive: {text!r}')
    return bytes([T_REM]) + b':' + tokenize_line(m.group(1), kw) + b'\x0d'


def add_directives(prog, directives=(), open_=False, lines=(), kw=None, fp=None):
    """Add 'REM : <directive>' lines, then 'REM : OPEN #' if open_, on free line numbers
    just below the first REM : OPEN # (directives must come before it; with open_, below
    the first line); and add or replace numbered lines given as 'N text'."""
    table = dict(tap.split_lines(prog))
    for e in lines:
        num, _, text = e.strip().partition(' ')
        if re.match(r'\s*REM\s*:', text):
            table[int(num)] = directive_line(text, kw)
        else:
            table[int(num)] = hide_numbers(tokenize_line(text, kw), fp) + b'\x0d'
    heads = list(directives) + (['OPEN #'] if open_ else [])
    if heads:
        opens = open_lines(tap.join_lines(sorted(table.items())))
        limit = min(table) if (open_ or not opens) and table else (min(opens) if opens else 10)
        free = [n for n in range(1, limit) if n not in table]
        if len(free) < len(heads):
            raise SourceError(f'no free line numbers for {len(heads)} directive line(s) before line {limit}')
        for n, d in zip(free[-len(heads):], heads):
            table[n] = directive_line('REM : ' + d, kw)
    return tap.join_lines(sorted(table.items()))


def tokenize_directives(prog, kw):
    """Spelled-out directives ('REM : INT a,b' in letters, as speccy-basic and the
    128 editor store them) -> token form, which is all v1.1 reads."""
    out = []
    for n, body in tap.split_lines(prog):
        if body[:1] == bytes([T_REM]):
            text = body[1:-1].decode('latin-1')
            if re.match(r'\s*:\s*[A-Za-z]', text):
                body = directive_line('REM ' + text.strip(), kw)
        out.append((n, body))
    return tap.join_lines(out)
