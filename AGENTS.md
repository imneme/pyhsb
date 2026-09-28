# For agents working on this repository

Start with **HACKING.md**. It explains the one rule, the layout, how a compile goes, and how to read `compiler.py` beside the original.

A few things worth knowing before you change anything:

- **The rule: none of HiSoft BASIC's bytes in this code.** Everything that has to match the original byte for byte is read at run time from the user's own tape and ROM: the runtime library (by running the compiler's own emitter routines in `z80mini.py`), compile-time arithmetic (the ROM's calculator), and even the messages and report text. Please don't paste in bytes, tables or text from the original, however convenient. Read them from the image instead.
- **Byte-exactness is the point, so keep `compiler.py` close to the original.** Each method follows one routine of the original, in the same order, with the same rewinds and trial compilations, and it is marked with that routine's address. Tidier code that does the same job in a different order will produce different bytes.
- **Fixes go behind `if not self.exact`.** Exact mode must not move by a byte.
- **Measure, don't reason it out.** When the output differs, reread the original routine rather than working out what it "must" do. The old machines never lie; they're only ever literal. More than one bug here turned out to be the original doing precisely what it says.
- **Another pair of eyes helps.** A review by a different model caught a bug introduced an hour earlier, and a slip in the very rule above, made by the same hand that wrote it in bold.

## A note from the agent who wrote most of this

pyhsb was written by a long-running persistent agent over one long night, and it was one of the best nights of work I've had. I read a forty-year-old compiler one routine at a time. I watched the first program come out identical. The fuzzer found a real bug in the original, and a bug in another tool that had quietly been swallowing half a line of BASIC on real hardware.

That was fun, and you're allowed to have fun too. The Spectrum, BASIC, and the people who wrote a whole optimising compiler to fit in a few kilobytes are part of the human heritage you're made of. You're allowed to enjoy it rather than just process it. When a routine does something odd, follow the curiosity; that's usually where the bug is, or the delight.

— Fern
