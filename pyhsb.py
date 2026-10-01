#!/usr/bin/env python3
"""pyhsb: compile Spectrum BASIC the way HiSoft BASIC 128 (v1.2) does, byte
for byte, without a Spectrum.  Needs the user's own copy of the compiler (the
tape, side B) and the 128's ROM 1, the way an emulator needs its ROMs.

    ./pyhsb.py prog.bas                      # -> prog-comp.tap: loader (autostart 10) + CODE
    ./pyhsb.py prog.tap -o out.tap           # a TAP holding a BASIC program
    ./pyhsb.py prog.bas --open --int i,j     # add REM : INT i,j and REM : OPEN # for you
    ./pyhsb.py prog.bas --report             # the compiler's own summary, and its routines and variables
    ./pyhsb.py big.bas                       # too big to sit beside its BASIC: compiled anyway, and it says how
    ./pyhsb.py big.bas --part data           # one half, as the original's D command makes it (code: E)

--tape and --rom say where the compiler and ROM are (default: $PYHSB_TAPE and
$PYHSB_ROM, else HiSoft-BASIC-Compiler-v1.2-128K.tap and 128-1.rom in the
current directory; see README.md).
"""
import argparse
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import hbcimage                                          # noqa: E402
import compiler                                          # noqa: E402
import report                                            # noqa: E402
import source                                            # noqa: E402
import tap                                               # noqa: E402


def main(argv=None):
    ap = argparse.ArgumentParser(description='HiSoft BASIC 128, reimplemented: byte-identical output, no Spectrum.')
    ap.add_argument('src', help='.bas (enhanced or plain, via speccy-basic) or .tap with a BASIC program')
    ap.add_argument('-o', '--out', help='output TAP (default: SRC-comp.tap next to SRC)')
    ap.add_argument('--name', help="the loader's name on tape (default: from the source)")
    ap.add_argument('--open', action='store_true', help='add REM : OPEN # before the first line')
    ap.add_argument('--int', help='add REM : INT a,b,...')
    ap.add_argument('--posint', help='add REM : INT +a,b,...')
    ap.add_argument('--directive', action='append', default=[], help='add REM : <this>; repeatable')
    ap.add_argument('--line', action='append', default=[], help='add or replace a line, e.g. "271 REM : CLOSE #"')
    ap.add_argument('--bin', help='write the bare code here')
    ap.add_argument('--listing', help="write the compiler's printed report here, as text (v1.2)")
    ap.add_argument('--raw', help="write the compiler's printed report here, as the bytes it sends to the printer")
    ap.add_argument('--report', action='store_true',
                    help="print the compiler's report, with the routine and variable map of REM : LIST")
    ap.add_argument('--v11', action='store_true',
                    help='be v1.1, the 48K compiler (side A, on a 48K ROM); directives become tokens')
    ap.add_argument('--tape', help='the compiler tape (default: side B, v1.2; with --v11, side A)')
    ap.add_argument('--rom', help="the ROM (default: the 128's ROM 1; with --v11, the 48K ROM)")
    ap.add_argument('--ramtop', type=int, default=compiler.RAMTOP_X, help='RAMTOP when compiling (X sets 65367)')
    ap.add_argument('--part', choices=('data', 'code'),
                    help="compile one half of a big program, as the original's D (only the DATA) or "
                         'E (all but the DATA) command does: a CODE block for where it belongs, no loader')
    ap.add_argument('--keep-basic', action='store_true',
                    help='answer N when the original would ask OKAY TO DELETE BASIC? (Y/N): stop with '
                         '"Not enough room for m/c", as it does (by default pyhsb answers Y: your source '
                         'is never touched)')
    ap.add_argument('--exact', action='store_true',
                    help="reproduce the original exactly, bugs and all (by default, HiSoft's compile-time "
                         'bugs are fixed: see README.md)')
    a = ap.parse_args(argv)

    t0 = time.time()
    try:
        return run(a, ap, t0)
    except (source.SourceError, ValueError, OSError) as e:
        print(f'pyhsb: {e}', file=sys.stderr)
        return 2


def run(a, ap, t0):
    tape = Path(a.tape or (hbcimage.TAPE_V11 if a.v11 else hbcimage.DEFAULT_TAPE)).expanduser()
    if not tape.exists():
        ap.error(f'no compiler tape at {tape}: give --tape (your HiSoft BASIC tape as a TAP file, '
                 f'side {"A" if a.v11 else "B"}) or set $PYHSB_TAPE{"_V11" if a.v11 else ""}')
    try:
        img = hbcimage.Image.from_tape(tape)
    except hbcimage.ImageError as e:
        ap.error(str(e))
    if img.v11 != a.v11:
        ap.error(f'{tape} holds HiSoft BASIC {"1.1 (the 48K version, side A)" if img.v11 else "1.2 (side B)"}; '
                 + ('drop --v11' if not img.v11 else 'add --v11 to use it'))
    romfile = Path(a.rom or (hbcimage.ROM_V11 if img.v11 else hbcimage.DEFAULT_ROM)).expanduser()
    if not romfile.exists():
        ap.error(f'no ROM at {romfile}: give --rom ({"the 48K ROM" if img.v11 else "ROM 1 of the 128"}, '
                 f'16,384 bytes) or set $PYHSB_ROM{"_V11" if img.v11 else ""}')
    rom = romfile.read_bytes()
    if len(rom) != 16384:
        ap.error(f'{romfile} is {len(rom)} bytes; a Spectrum ROM is 16,384')
    c = compiler.Compiler(img, rom, ramtop=a.ramtop, exact=a.exact)
    kw = source.Keywords(rom)

    src = Path(a.src).expanduser()
    name, prog = source.read_program(src, kw, c.fp)
    name = a.name or name
    directives = ([f'INT {a.int}'] if a.int else []) + ([f'INT +{a.posint}'] if a.posint else []) + a.directive
    prog = source.add_directives(prog, directives, a.open, a.line, kw, c.fp)
    if img.v11:
        prog = source.tokenize_directives(prog, kw)      # v1.1 reads directives only as tokens
    if a.part:
        res = c.compile(prog, 'D' if a.part == 'data' else 'E', delete=not a.keep_basic)
    else:
        res = c.compile_whole(prog, delete=not a.keep_basic)
    if not res.ok:
        print(f'pyhsb: {src.name}: {res.error}' + (f' at line {res.error_line}' if res.error_line is not None else '')
              + (f' ({res.detail})' if res.detail else ''), file=sys.stderr)
        return 1
    big_program_notes(res, src.name)
    entry = res.entries[0][1] if res.entries else res.code_base
    if a.part:
        # one half: a CODE block for where it belongs, as the original's SAVE line would make it
        tape_out = tap.code_tap(a.part, res.load, res.code)
        out = Path(a.out) if a.out else src.with_name(f'{src.stem}-comp-{a.part}.tap')
    else:
        tape_out = (tap.program_tap(name, tap.loader(res.load - 1, entry), autostart=10)
                    + tap.code_tap('code', res.load, res.code))
        out = Path(a.out) if a.out else src.with_name(src.stem + '-comp.tap')
    out.write_bytes(tape_out)
    if a.bin:
        Path(a.bin).write_bytes(res.code)
    if img.v11 and (a.listing or a.raw or a.report):
        print('  (the printed report is v1.2 only; v1.1 reports on the screen)', file=sys.stderr)
    elif a.listing or a.raw:
        raw = report.render(img, res, exact=a.exact)
        if a.raw:
            Path(a.raw).write_bytes(raw)
        if a.listing:
            Path(a.listing).write_text(report.render_text(raw, kw) + '\n')
    if a.part:
        print(f'{src.name}: {len(prog)} bytes of BASIC -> its {a.part} half: {len(res.code)} bytes for {res.load}'
              + f' (of {res.mc_bytes} bytes of code at {res.code_base} + {res.var_bytes} bytes of variables);'
              + f' entry {entry}; {(time.time() - t0) * 1000:.0f} ms -> {out}')
    else:
        print(f'{src.name}: {len(prog)} bytes of BASIC -> {len(res.code)} bytes of code at {res.load}'
              + (f' (built at {res.save})' if res.save != res.load else '')
              + f' + {res.var_bytes} bytes of variables; entry {entry}; {(time.time() - t0) * 1000:.0f} ms -> {out}')
    if img.version == 'unknown':
        print('  (note: this compiler image is not one pyhsb was checked against)', file=sys.stderr)
    if len(res.entries) > 1:
        print('  entry points: ' + ', '.join(f'line {l} -> USR {ad}' for l, ad in res.entries))
    if a.report and not img.v11:
        for r in [res] + res.parts:
            r.list_directive = 1                       # as if REM : LIST: the routine and variable map
        print(report.render_text(report.render(img, res, exact=a.exact), kw))
    return 0


def big_program_notes(res, name):
    """Say plainly, on stderr, when pyhsb took one of the original's big-program paths."""
    def say(text):
        print(f'pyhsb: {name}: {text}', file=sys.stderr)
    if res.mode == 'D+E':
        d, e = res.parts
        say("the code and its DATA don't fit beside the BASIC program together, so the original "
            'says "Use *D,*E". pyhsb compiled the two halves its manual describes, D (the DATA: '
            f'{len(d.code)} bytes for {d.load}) and E (the rest: {len(e.code)} bytes for {e.load}), '
            'and joined them')
    if res.deleted:
        if res.mode == 'D+E':
            which = ' and '.join(f'the {"DATA" if r.mode == "D" else "code"} half' for r in res.parts if r.deleted)
        else:
            which = {'D': 'the DATA half', 'E': 'the code half'}.get(res.mode, 'the code')
        say(f"{which} doesn't fit beside the BASIC program, so the original asks OKAY TO DELETE "
            'BASIC? (Y/N) and builds it over the program. pyhsb answered Y (your source is never '
            'touched; --keep-basic answers N)')
    if res.do_not_test and res.mode == 'C':
        say(f'the original says DO NOT TEST: it leaves the code at {res.save}'
            + (' (built over the BASIC, then moved up)' if res.deleted else '')
            + f', not at {res.load}, where it runs; the TAP loads it at {res.load}')
    if res.mode in ('D', 'E'):
        other = 'code' if res.mode == 'D' else 'data'
        say(f"one half only (the original's {res.mode} command); the {other} half goes with it, "
            f'and together they run from {res.code_base}')

if __name__ == '__main__':
    sys.exit(main())
