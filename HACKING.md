# Hacking on pyhsb

pyhsb is a reimplementation, in Python, of the compiler in **HiSoft BASIC 1.2 for the ZX Spectrum 128** (Cameron Hayne, 1986–87). Given the same BASIC program and directives, it produces the same machine code as the original, byte for byte: the same code, runtime routines, DATA, variable layout and load address. It also produces the same printed report. It runs anywhere Python 3.10+ does, in milliseconds, with no emulator.

This guide is for reading and changing it. For using it, see README.md.

## The one rule: no HiSoft bytes

pyhsb contains none of HiSoft BASIC's code or data. Everything that has to match the original byte for byte is read at run time from **the user's own copy**: the compiler tape and the Spectrum ROM, the way an emulator asks for ROMs.

- **The runtime library** (about 1.5 KB of routines that compiled programs call) is not stored in the compiler as a blob. For each routine the compiler has a small *emitter*, Z80 code that writes the routine out from inline fragments, with calls in between for the parts that hold addresses. pyhsb runs those emitters, from the user's tape, in a small Z80 interpreter (`z80mini.py`), and collects what they write.
- **Compile-time arithmetic** (folding `-5` into a literal, rounding a constant to an integer, `VAL "..."`) is done by the ROM's own floating-point calculator, run in the same interpreter (`romfp.py`), so the results match to the bit. Some library routines are copies of ROM code, so the ROM is needed for those too.
- **The words in the printed report** come from the compiler's message tables in the user's image.
- **The code generator is ours.** `compiler.py` follows the original's logic routine by routine, and writes the instructions it emits as Z80 mnemonics (`z80asm.py`), never as hex.

Please keep it that way: no byte strings copied from the compiler, no pasted tables, no fragments in hex.

## Layout

The compiler itself (standard library only; speccy-basic is optional, for `.bas` files with labels or the enhanced syntax):

| File | What |
|---|---|
| `pyhsb.py` | the command line |
| `compiler.py` | the compiler: the driver, passes, statements, the expression compiler |
| `rtlib.py` | the runtime library: runs the user's emitters, lays the routines out |
| `z80mini.py` | a small Z80 interpreter (complete decoder, no timing, no I/O) |
| `z80asm.py` | a tiny assembler for the fragments the compiler emits |
| `romfp.py` | compile-time arithmetic on the ROM's calculator, with integer fast paths |
| `hbcimage.py` | finds the compiler on the tape; names the version by hash |
| `source.py` | BASIC text → program bytes, the ROM's way; reading `.bas` / `.tap`; adding directive lines |
| `tap.py` | TAP files, program lines, the loader |
| `report.py` | the compiler's printed report |
| `rtnames.py` | our names for the runtime routines (`RT.REAL_STORE` is 108), used throughout `compiler.py` |
| `tests/` | unit tests that need only the tape and ROM (`python3 -m unittest discover -s tests`) |

## Reading it next to the original

Each method in `compiler.py` is marked with the address of the routine it follows (`# D00A` is the add/subtract level of the expression compiler in v1.2). The structure is kept deliberately close to the original's, because byte-for-byte output depends on doing the same things in the same order. That includes rewinding, trial compilations and the order in which routines are marked as used.

Some conventions of the translation:

- **CH_ADD is an index.** The original copies each line into a buffer and walks it with the ROM's `RST 18` (GET_CHAR) and `RST 20` (NEXT_CHAR), which skip spaces and colour codes. `get_char()`, `next_char()` and `skip_over()` do the same to `self.buf`.
- **Emitting.** `emit_byte`, `emit_word`, `emit_word_reloc` (adds the load address), `call_rt(n)` (a `CALL` to runtime routine n, marking it used), and `emit('ld hl,$2758; exx; ret')` for a fragment. Code is only stored in pass 2 (`self.storing`); in passes 0 and 1 only the program counter moves.
- **Rewinding.** `save_state()` / `restore_state(st)` save and restore both CH_ADD and the code PC; `rewind_code(st)` restores only the PC. The original uses this to compile an operand, look at the type it produced, and recompile differently.
- **Probing.** To specialise `a*2`, `a+1` or `INT (a/4)`, the compiler compiles the right operand as a *probe* (`probe(fn)`), which reports whether it was a small constant, a power of two or an integer variable. Anything complicated ends the probe early: `probe_abort()` returns True, and the level that noticed returns at once (`if self.probe_abort(): return`). Then the probe's code is rewound and the special form emitted. The values `probe_simple` and `probe_pow2` can take are listed in a comment above `probe_abort`.
- **Runtime routines by name.** `call_rt(RT.STACK_CONST)` is `CALL` to routine 110. The names and their one-line descriptions (`rtnames.py`) are ours, from reading the routines; the numbers are the compiler's.
- **Types.** `self.t` is the type of the value just compiled: 0 REAL, 1 INTEG (signed 16-bit), 2 POSINT (unsigned), 3 a constant that fits both, 0x80 string. `convert_type(d)` emits the conversion.

## How a compile goes

`Compiler.compile(prog)` → `_compile`:

1. **Pass 0** (counting, `pass0`): directives are read (only here, and only before the first `REM : OPEN #`), variables are entered in the name table in order of appearance, and every constant GO TO / GO SUB / RESTORE target is added to the line table. The whole code generator runs, but nothing is stored.
2. The routine table is cleared.
3. **Pass 1** (counting): the whole generator again, now with every variable's type known. Each compiled line's address is recorded in the line table. At the end the runtime routines are laid out (`rtlib.Machine.layout`), and for computed jumps the line table is emitted after them.
4. **Addresses**: DATA starts after pass 1's code, then the variables (simple variables, integers first; then FOR limits and steps for letters a..z; arrays; strings), and the whole block is placed just below RAMTOP.
5. **Pass 2** (storing): the generator runs a third time and writes. Forward jumps are patched as their targets become known: IF's `JP Z` at the end of its line, FOR's `JP` by its NEXT, DEF FN's `JP` at the end of its body.

The routine layout runs at the end of every pass. A routine that falls through into the next one marks it as used while it is being laid out.

Statements are dispatched by token (`dispatch`), expressions go down the levels `expr` (OR) → `expr_and` → `expr_compare` → `expr_add` → `expr_mul` → `expr_power` → `operand`.

## The runtime library

`rtlib.Machine` owns the Z80 interpreter's 64K memory. The compiler's image goes where it loads, and the ROM at 0. The routine table (131 × 3 bytes: a used flag and an address) sits at 0x4000, as in the original, and so do the variables the emitters read: code PC, load address, and whether this pass stores. So the emitters' own calls to mark a routine used work unchanged. In v1.2 the emitters write through the 128's paging stub (outside the image), and those few entry points are hooked in Python. v1.1 writes straight into memory, and a staging area is copied out.

`layout(pc, counting, code_base)` is the original's layout loop: every marked routine, in number order, gets the current PC and its emitter is run.

## Exact and fixed

`Compiler(image, rom, exact=False)` fixes the original's compile-time bugs; `exact=True` reproduces them, and every comparison with the original uses exact. Each fix sits at an `if self.exact` / `if not self.exact` in `compiler.py`, and `report.render(..., exact=)` for the report:

- **Dropping a number no longer crashes the machine.** Where the compiler reads a number and then finds it isn't a constant after all, it discards it by rounding it to an integer. That's harmless unless the number is out of range: then the ROM's error has no handler mid-compile, and the original resets the 128, or reports a wrong error. Fixed: the number is just dropped (`drop_number`).
- An out-of-range constant that is actually used is an ordinary compile error, "Integer out of range".
- Line numbers of 16384 and up can't exist, and they break the line table (bits 6 and 7 of its line numbers are flags): "Non-existent line".
- The printed report uses the intended TAB columns.
- Bytes the compiler skips without writing (DEF FN's parameter slots) are zeros, not whatever was in memory.

The runtime library's own trade-offs (no bounds checks, string lengths not enforced, wrap-around in integers) are the original's design, not bugs, and pyhsb keeps them: changing them would mean a different library.

To add a fix: put it behind `if not self.exact`, and make sure exact mode doesn't move by a byte.

## How it was checked

pyhsb was written against the original, and every change was checked by compiling the same programs both ways and comparing byte for byte. The original ran on an emulated Spectrum 128, driven headless, with its report caught at the printer channel; about 0.15 s per program, with answers cached by program bytes. That rig depends on an emulator setup that isn't part of this repository, but it's worth describing, because anyone changing pyhsb will want one:

- **The comparison** covered everything the original produces: the code block, the load and build addresses, the variables' size, the `LINE n:` entry points, the printed report, and the whole TAP with its loader. On a mismatch it gave the first differing address, the BASIC line it fell in, and both disassemblies there, which was usually enough to find the routine to reread.
- **The programs**: the tape's own examples through the manual's tutorial steps; real games; a directed case for every directive and statement form, including every error the compiler reports; and a grammar-driven generator of random valid programs (mixed REAL/INTEG/POSINT variables, arrays, strings, DEF FN, directives in random combination), whose failures were minimised by removing lines and statements while the difference remained. Thousands of generated programs came out identical, for both versions.
- **Programs the original crashes on** (an out-of-range constant rounded mid-compile: see "Exact and fixed") were matched against pyhsb's "Integer out of range" at the same line.
- **Program bytes** for tests were stored the way the ROM stores a line (`source.tokenize`), since some tools that turn text into Spectrum BASIC don't write the hidden number after `BIN`.

To build your own oracle, any emulator that can load the tape, run the compiler (on a 128: TRUE VIDEO + INV VIDEO, then C; `X` first sets RAMTOP to 65367, as pyhsb assumes by default) and let you read memory afterwards will do. The compiler's final report gives the code's address and length.

## Things that were surprising

- **Some library routines are copies of the ROM** (string comparison, RND, INKEY$, ATTR). Without the ROM the library matches in every address but not in bytes.
- **The ROM's rounding is not Python's.** `VAL "0.5"` makes 0.4999999998, and adding 0.5 rounds up to 1. Only running the ROM gets such cases right, which is why `romfp.py` exists.
- **The line table lives on top of other code** (in v1.2, the installer's leftovers in the compiler's bank). A lookup that runs off its end reads those bytes, and pyhsb keeps the table as bytes in the same place so it reads the same ones.
- **A line can hide its REM behind colour codes**, because GET_CHAR skips them.
- **The compiler stays in ordinary RAM after installing itself**, so bytes it never writes can hold its own image.

## Versions

- **v1.2 for the 128** is the default, and the one the compiler targets; its code also runs on a 48K.
- **v1.1 for the 48K** (the tape's other side) is supported with `--v11`. It's the same compiler with small differences, each marked `v1.1` in `compiler.py`: keywords matched as tokens only; no BREAK or VAL directives, and a `REM : LPRINT` directive; no PLAY or VAL$; BEEP and COPY call the ROM directly; a different home for the line and name tables; lines compiled in place.
- The +3 disk version isn't supported.
