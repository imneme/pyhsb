# pyhsb

A compiler for ZX Spectrum BASIC that produces **exactly** what the HiSoft BASIC compiler produces, byte for byte, without a Spectrum or an emulator.

[HiSoft BASIC](http://hayne.net/Spectrum/HiSoftBASIC/) was written by Cameron Hayne and published by HiSoft in 1986–87: a compiler that turned an ordinary Spectrum BASIC program into fast machine code, run on the Spectrum itself. pyhsb is an independent reimplementation of its compiler in Python, for version 1.2 (the Spectrum 128 version, whose code also runs on a 48K) and version 1.1 (the 48K version).

```
$ ./pyhsb.py circle2.bas
circle2.bas: 579 bytes of BASIC -> 853 bytes of code at 64473 + 42 bytes of variables; entry 64473; 81 ms -> circle2-comp.tap
```

The output is a TAP with a loader (`CLEAR`, `LOAD ""CODE`, `RANDOMIZE USR`) and the compiled code, ready for any Spectrum or emulator. The code runs on a 48K as well as a 128.

## What you need

- **Python 3.10 or later.** Nothing else, except [spectrum-basic](https://pypi.org/project/spectrum-basic/) (`pip install spectrum-basic`) if your `.bas` files have unnumbered lines, labels or its enhanced syntax. Plain numbered BASIC and `.tap` files need nothing.
- **The HiSoft BASIC tape**, as a TAP file. pyhsb contains none of HiSoft BASIC's code: it reads the runtime routines, and the text of its messages and report, from the tape at run time, the way an emulator reads a ROM. The tapes, converted to TAP:

  ```
  curl -OL https://www.cs.hmc.edu/~oneill/spectrum/classics/HiSoft-BASIC-Compiler-v1.2-128K.tap
  curl -OL https://www.cs.hmc.edu/~oneill/spectrum/classics/HiSoft-BASIC-Compiler-v1.1-48K.tap
  curl -OL https://www.cs.hmc.edu/~oneill/spectrum/classics/HiSoft-BASIC-Compiler-v1.2-Plus3.dsk
  ```

  (The +3 disk isn't used by pyhsb; it's there for completeness. Other archives, such as World of Spectrum, have the tapes too, usually as TZX.)
- **The Spectrum ROM**: ROM 1 of the Spectrum 128, the one holding 48 BASIC (16,384 bytes); emulators such as [Fuse](https://fuse-emulator.sourceforge.net/) ship it as `128-1.rom`. For v1.1, the 48K ROM (`48.rom`). The compiler ran with the ROM paged in: it does its compile-time arithmetic with the ROM's calculator, and some runtime routines are copies of ROM code.

Keep the tape and ROM in the current directory under those names, or pass `--tape` and `--rom`, or set `PYHSB_TAPE` and `PYHSB_ROM` (`PYHSB_TAPE_V11` and `PYHSB_ROM_V11` for v1.1).

## Using it

```
./pyhsb.py prog.bas                        # -> prog-comp.tap
./pyhsb.py prog.tap -o out.tap             # a TAP holding a BASIC program
./pyhsb.py prog.bas --open                 # add REM : OPEN # at the start
./pyhsb.py prog.bas --int a,b --posint c   # add REM : INT a,b and REM : INT +c
./pyhsb.py prog.bas --directive 'GOSUB :'  # any REM : directive
./pyhsb.py prog.bas --line '271 REM : CLOSE #'
./pyhsb.py prog.bas --listing prog.lst     # the compiler's printed report, to a file (--raw: as bytes)
./pyhsb.py prog.bas --report               # the report on the terminal, with the routine and variable map
./pyhsb.py prog.bas --bin prog.bin         # also the bare code
./pyhsb.py prog.bas --name GAME            # the loader's name on tape (default: the file's)
./pyhsb.py prog.bas --ramtop 40000         # compile below another RAMTOP (the original's X command sets 65367)
./pyhsb.py prog.bas --exact                # reproduce the original exactly, bugs and all
./pyhsb.py prog.bas --v11                  # HiSoft BASIC 1.1, the 48K version (its tape, and 48.rom)
```

The directives (`REM : OPEN #`, `REM : INT ...`, `REM : LEN ...` and the rest) are the original's; see its manual.

## Bugs fixed

By default pyhsb fixes the original's compile-time bugs. `--exact` turns the fixes off.

- The original resets the Spectrum on some programs with a constant beyond ±65535 (for example `LET p(70000/i,3)=...`). pyhsb compiles them, or reports "Integer out of range".
- A line number of 16384 or more in `GO TO`, `GO SUB` or `RESTORE` confuses the original's line table, which uses those bits as flags; from 32768 up it reads past the table's end and jumps to a garbage address. No program line can have such a number, so pyhsb reports "Non-existent line".
- The printed report puts every field on its own line, a bug in its printer TAB handling; pyhsb uses the intended columns.
- Bytes the original skips without writing (DEF FN's parameter slots) hold whatever was in memory; pyhsb writes zeros.

Not supported: when there isn't room for the code and its variables, the original offers to delete the BASIC program to make room; pyhsb reports "Not enough room" instead.

## How it was checked

pyhsb was developed against the original: every test program was compiled both by pyhsb and by the real compiler running on an emulated Spectrum, and the results compared byte for byte (code, load address, variable layout, the loader TAP and the printed report). That covered the tape's example programs, real games, a directed case for every directive and statement form, and thousands of randomly generated programs, for both versions. That test rig depends on an emulator setup that isn't part of this repository; the unit tests here (`python3 -m unittest discover -s tests`) check the parts that need only the tape and ROM. See HACKING.md.

## Provenance

HiSoft BASIC was written by Cameron Hayne and published by HiSoft (1986–87); see [his page about it](http://hayne.net/Spectrum/HiSoftBASIC/). pyhsb is an independent reimplementation, written by a long-running persistent AI agent (Fern, Claude Opus 5.5) working with Melissa O'Neill, who takes responsibility for it. It was built by reading the original's machine code and translating its logic, and checked against the original throughout; it contains none of the original's code or text.
