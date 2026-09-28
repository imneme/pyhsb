"""The runtime library's routines, by number (1..131), with our names for them.

The numbers are the compiler's own (its routine table, and the RTn in its REM : LIST
report); the names and one-line descriptions are ours, from reading the routines.
Slots 42, 43 and 46 are empty in v1.2 (42 and 43 are the +3's disk streams).
"""


class RT:
    INT_LE_POSINT = 1       # HL=1 if HL(INTEG) <= DE(POSINT), else 0: swaps and falls into RT2
    POSINT_GE_INT = 2       # HL=1 if HL(POSINT) >= DE(INTEG): HL>=32768 gives 1, otherwise a signed compare via RT12
    POSINT_GT_INT = 3       # HL=1 if HL(POSINT) > DE(INTEG): swaps and falls into RT4
    INT_LT_POSINT = 4       # HL=1 if HL(INTEG) < DE(POSINT): negative HL gives 1, otherwise an unsigned compare via RT20 (QUIC...
    MIXED_NE = 5            # HL=1 if HL <> DE, one INTEG and one POSINT in either order: HL bit 15 set gives 1, otherwise RT22
    POSINT_LE_INT = 6       # HL=1 if HL(POSINT) <= DE(INTEG): swaps and falls into RT7
    INT_GE_POSINT = 7       # HL=1 if HL(INTEG) >= DE(POSINT): negative HL gives 0, otherwise an unsigned compare via RT18
    INT_GT_POSINT = 8       # HL=1 if HL(INTEG) > DE(POSINT), e.g. IF c>7 with INT c: swaps and falls into RT9
    POSINT_LT_INT = 9       # HL=1 if HL(POSINT) < DE(INTEG): HL>=32768 gives 0, otherwise a signed compare via RT15
    MIXED_EQ = 10           # HL=1 if HL = DE, one INTEG and one POSINT in either order: HL bit 15 set gives 0, otherwise RT21...
    INT_LE = 11             # HL=1 if HL <= DE (signed INTEG): swaps and falls into RT12
    INT_GE = 12             # HL=1 if HL >= DE (signed): SBC HL,DE, sign corrected with XOR $80 on overflow (P/V), then RT13
    SIGN_TO_GE = 13         # tail of RT12: HL=0 if the S flag is set, else 1 (it has a number only because RT12 jumps here)
    INT_GT = 14             # HL=1 if HL > DE (signed): swaps and falls into RT15
    INT_LT = 15             # HL=1 if HL < DE (signed), overflow corrected as in RT12, then RT16
    SIGN_TO_LT = 16         # tail of RT15: HL=1 if the S flag is set, else 0
    POSINT_LE = 17          # HL=1 if HL <= DE (unsigned POSINT): swaps and falls into RT18
    POSINT_GE = 18          # HL=1 if HL >= DE (unsigned) (QUICKSOR: I>=J)
    POSINT_GT = 19          # HL=1 if HL > DE (unsigned), e.g. IF k>size: swaps and falls into RT20
    POSINT_LT = 20          # HL=1 if HL < DE (unsigned)
    INT_EQ = 21             # HL=1 if HL = DE (compares the 16-bit pattern, so it serves INTEG and POSINT)
    INT_NE = 22             # HL=1 if HL <> DE (16-bit pattern)
    STR_GE = 23             # HL=1 if A$ >= B$ (both popped from the calc stack, B$ on top): swaps the strings, then RT24
    STR_LE = 24             # HL=1 if A$ <= B$: A=4, then RT29
    STR_LT = 25             # HL=1 if A$ < B$: swaps the strings, then RT26
    STR_GT = 26             # HL=1 if A$ > B$: A=6, then RT29
    STR_NE = 27             # HL=1 if A$ <> B$: A=5, then RT29
    STR_EQ = 28             # HL=1 if A$ = B$: A=7, falls into RT29
    STR_COMPARE = 29        # pops B$ then A$, compares bytes unsigned (a prefix is smaller); A bit 0 = answer if equal, bit 1...
    PRINT_STR = 30          # PRINT a string expression: pops it from the calc stack, then PR_STRING
    PRINT_POSINT = 31       # PRINT a POSINT in HL: stacked by RT111, then PRINT_FP
    PRINT_INT = 32          # PRINT an INTEG in HL: stacked by RT112, then PRINT_FP
    STR_CHAR = 33           # s$(i): HL=i; the stack holds the text address and length (length ignored); stacks 1 char at text+...
    STR_SLICE_FROM = 34     # s$(a TO): HL=a; the stack holds the text address and length (the length is the end); via RT37
    STR_SLICE_TO = 35       # s$( TO b): HL=b; the stack holds only the text address; start=1; via RT37 (EXAMPLE2: N$( TO L-I))
    STR_SLICE = 36          # s$(a TO b): HL=b; the stack holds the text address, the length (dropped with INC SP x2) and a; vi...
    STR_SLICE_CORE = 37     # shared tail: BC=a, DE=b, EX (SP),HL swaps the text address for the return address; stacks text+a-...
    PLAY = 38               # PLAY: strings on the calc stack, count in BC; in 48K mode (FLAGS bit 4 clear) only SET_WORK, so i...
    COPY = 39               # COPY: in 48K mode, jumps to ROM COPY; in 128 mode, calls ROM 0 $012A (128/+2) or +3 ROM 1 $20D3,...
    BEEP = 40               # BEEP: duration and pitch on the calc stack, ROM BEEP, with IX preserved
    BREAK_CHECK = 41        # BREAK_KEY; if BREAK is pressed, error L (RST 8 + $14); for REM : BREAK
    EMPTY_42 = 42           # no routine: its entry in the emitter table (0xE071) is 0, so forcing it jumps to address 0 and re...
    EMPTY_43 = 43           # no routine: its entry in the emitter table (0xE071) is 0, so forcing it jumps to address 0 and re...
    VAL_STR = 44            # VAL$: the string on the calc stack is evaluated by ROM val$ (B=$18); the result string is left on...
    ERR_SP_RESTORE = 45     # new in v1.2 together with VAL and VAL$ (absent in the 48K v1.1), so probably part of VAL's error...
    EMPTY_46 = 46           # no routine: its entry in the emitter table (0xE071) is 0, so forcing it jumps to address 0 and re...
    PRINT_LIT = 47          # PRINT "literal": the 2-byte length and text follow the CALL inline; prints them and returns past...
    STACK_LIT = 48          # a string literal in an expression: the inline 2-byte length and text after the CALL are stacked (...
    READ_STR = 49           # READ a$: the DATA item at S_TOP (2-byte length + text) is stacked as a string and S_TOP advances;...
    READ_INT = 50           # READ into INTEG/POSINT: HL = the 2-byte DATA item at S_TOP; S_TOP += 2
    READ_REAL = 51          # READ into a REAL: the 5-byte DATA item at S_TOP goes to the calc stack (STACK_NUM); S_TOP += 5
    INPUT_TRAP_ON = 52      # start of INPUT: saves its return address in OLDPPC ($5C6E) as the restart point; pushes CH_ADD, E...
    INPUT_RETRY = 53        # INPUT's error handler, reached via ERR_SP on any error during INPUT: pushes itself again, ERR_NR=...
    INPUT_TRAP_OFF = 54     # end of INPUT: ROM INPUT's tail at $20A0 (S_POSN, SCR_CT, clear the lower screen), SET_WORK; pops...
    PAUSE = 55              # PAUSE HL: BC=HL, clears FLAGS bit 5 (key flag), jumps to ROM PAUSE_1
    INPUT_START = 56        # INPUT prelude, as in the ROM: open channel K, CLS_LOWER, TV_FLAG=1
    INPUT_INT = 57          # INPUT into INTEG/POSINT: RT58, then RT61; the value is in HL
    INPUT_REAL = 58         # INPUT a number: RT59, then VAL (RT109), so any expression VAL accepts works; the value is on the...
    INPUT_STR = 59          # INPUT a string: RT60, then stacks the typed line from WORKSP up to the CR (no quotes, so it behav...
    INPUT_EDIT = 60         # keyboard entry into the workspace: a copy of the ROM's INPUT editing core (FLAGX bits, EDITOR, K_...
    REAL_TO_INT = 61        # pops a REAL and rounds it (adds +/-0.49999999988, truncates) into HL (16 bits); error B only if |...
    USR_UDG = 62            # USR "a": the string on the calc stack becomes a UDG address in HL (ROM usr-$ then INT_FETCH)
    USR_CALL = 63           # USR n: calls machine code at HL with BC=HL, then restores IY and reselects stream 2; HL = the BC...
    INT_ARR_GET = 64        # integer array element: HL = word at DE+2*(HL-1) (DE = array base, HL = 1-based index); no bounds...
    REAL_ARR_GET = 65       # REAL array element to the calc stack: STACK_NUM from DE+5*(HL-1)
    REAL_ARR_ADDR = 66      # REAL array element address: HL = DE+5*(HL-1), for assignment with RT108
    STR_DESC_AT = 67        # DE = bytes 1-2, BC = bytes 3-4 of the 5-byte entry at HL (a string's start and length in calc-sta...
    STR_ARR_ELEM = 68       # string array row: DE = array (2-byte element length, then the data), HL = 1-based index; returns...
    STR_ASSIGN = 69         # LET s$=...: pops the string into the variable at HL (2-byte length, then LDIR of the text); no ch...
    STR_VAR_STACK = 70      # stacks the string variable at HL (2-byte length + text) on the calc stack
    STR_VAR_GET = 71        # string variable at HL gives DE = text address, BC = length (for LEN and subscripts)
    REAL_COMPARE = 72       # HL=1 if x OP y (both REALs popped): the caller passes the calculator's comparison code in B ($09...
    REAL_COPY_KEEP = 73     # copies the top REAL to (DE) without popping it; REAL FOR stores its start and limit this way
    FOR_REAL_INIT = 74      # REAL FOR: DE = step slot (limit slot at DE-5); pops the step into it, swaps start and limit, then...
    NEXT_REAL = 75          # REAL NEXT: DE = the variable, HL = the limit slot (step at HL+5); var += step, then RT76; NZ = lo...
    FOR_REAL_TEST = 76      # HL = step slot: pops limit-var (var-limit if step<0) and tests its sign; Z = keep looping, NZ = done
    REAL_OR_INT = 77        # x OR n (x a REAL on the calc stack, n in HL): x becomes 1 if n<>0
    REAL_OR = 78            # x OR y, both REALs: ROM or, called directly
    INT_OR_REAL = 79        # n OR y (n pushed on the machine stack, y a REAL on the calc stack): HL = n if y=0, else 1
    STR_AND_INT = 80        # a$ AND n (a$ on the calc stack, n in HL): the length is set to 0 if n=0 (EXAMPLE5: "S" AND (N>1))
    STR_AND_REAL = 81       # a$ AND y, y a REAL: ROM str-&-no
    REAL_AND = 82           # x AND y, both REALs: ROM no-&-no
    REAL_AND_INT = 83       # x AND n (x a REAL, n in HL): x becomes 0 if n=0
    INT_AND_REAL = 84       # n AND y (n pushed, y a REAL on the calc stack): HL = n if y<>0, else 0
    REAL_MUL = 85           # x*y: ROM multiply called directly, with pointers from RT114
    REAL_DIV = 86           # x/y: ROM division called directly
    REAL_SCALE_POW2 = 87    # the top REAL times 2^A (A signed), by adjusting the exponent; error 6 on overflow, 0 on underflow...
    REAL_CUBE = 88          # the top REAL x becomes x*x*x (RST 28: duplicate, duplicate, multiply, multiply); probably for x^3
    REAL_ADD = 89           # x+y: ROM addition called directly
    REAL_SUB = 90           # x-y: ROM subtract called directly
    INT_NOT = 91            # NOT n for an integer: HL=1 if HL=0, else 0
    REAL_NOT = 92           # NOT x for a REAL: pops it; HL=1 if x=0, else 0
    REAL_NEG = 93           # unary minus on the top REAL (ROM negate)
    REAL_ABS = 94           # ABS of the top REAL (ROM abs)
    REAL_SGN = 95           # SGN of the top REAL (ROM sgn)
    INT_SHR = 96            # HL arithmetic shift right B times, i.e. INT (n/2^B) for INTEG
    POSINT_SHR = 97         # HL logical shift right B times, i.e. INT (n/2^B) for POSINT
    POSINT_DIV_INT = 98     # INT (HL/DE) with HL POSINT and DE INTEG: the sign of DE goes to BREG, then RT101
    INT_DIV_POSINT = 99     # INT (HL/DE) with HL INTEG and DE POSINT: if DE>=32768, HL = 0 or -1 by HL's sign, otherwise RT100
    INT_DIV = 100           # INT (HL/DE), both INTEG: the result's sign (H xor D) goes to BREG, HL=|HL|, then RT101
    DIV_SIGNED_TAIL = 101   # DE=|DE|, unsigned RT102; if BREG is negative, the quotient becomes -(q+1) when there's a remainde...
    POSINT_DIV = 102        # unsigned HL/DE: HL = quotient, DE = remainder; error 6 if DE=0 (EXAMPLE6: INT (704/LEN C$))
    INT_CUBE = 103          # HL = HL*HL*HL (RT104 twice); probably n^3
    INT_MUL = 104           # HL = HL*DE mod 65536, no overflow check; repeated addition when DE<=32, otherwise a 16-bit shift-...
    INT_ABS = 105           # ABS for INTEG: negates HL if it's negative; also used by the division routines
    INT_SGN = 106           # SGN for INTEG: HL = -1, 0 or 1
    INT_TO_BOOL = 107       # HL=1 if HL<>0, else 0 (normalises a truth value); no program uses it, so its caller is unknown
    REAL_STORE = 108        # LET for a REAL: pops the top of the calc stack into the 5 bytes at DE
    VAL = 109               # VAL: the string on the calc stack is evaluated by ROM val (B=$1D) into a number; INPUT uses it too
    STACK_CONST = 110       # stacks the 5-byte float that follows the CALL inline and returns after it
    STACK_POSINT = 111      # stacks POSINT HL on the calc stack as a small integer
    STACK_INT = 112         # stacks INTEG HL on the calc stack as a small integer (sign byte $FF if negative)
    REAL_SWAP = 113         # swaps the top two calc stack entries (ROM exchange)
    CALC_PTRS = 114         # HL = STKEND-10 (first operand), DE = STKEND-5 (second): the set-up for calling ROM calculator ops...
    REAL_POP_ZERO = 115     # pops the top REAL; carry set if it was zero; HL=0; for IF on a REAL and the NOT/AND/OR helpers
    INK = 116               # INK L: CO_TEMP_5 with A=$10, D=L (sets the temporary colour variables)
    PAPER = 117             # PAPER L: CO_TEMP_5 with A=$11
    FLASH = 118             # FLASH L: CO_TEMP_5 with A=$12
    BRIGHT = 119            # BRIGHT L: CO_TEMP_5 with A=$13
    INVERSE = 120           # INVERSE L: CO_TEMP_5 with A=$14
    OVER = 121              # OVER L: CO_TEMP_5 with A=$15
    PRINT_AT = 122          # PRINT AT E,L: sends 22, E (line), L (column) through RST 10
    PRINT_TAB = 123         # PRINT TAB L: sends 23, L and a second (ignored) byte through RST 10
    STREAM_SCREEN = 124     # opens stream 2 (main screen); used by every program's prologue, at the end of INPUT and after CLS
    STREAM_PRINTER = 125    # opens stream 3 (printer), presumably for LPRINT and LLIST
    MEM_FILL = 126          # fills BC+1 bytes at HL with A (LD (HL),A then LDIR); probably DIM clearing arrays (every program...
    RND = 127               # RND: a copy of the ROM's routine (SEED = (75*(SEED+1) mod 65537)-1, divided by 65536); the result...
    INKEY_STR = 128         # INKEY$: a copy of the ROM's key read; stacks a 1-character or empty string
    POINT = 129             # POINT (C=x, B=y): HL = pixel bit 0/1 (PIXEL_ADD, which gives error B if y>175)
    ATTR = 130              # ATTR (C=line, B=column): HL = attribute byte; a copy of the ROM's code without its range check
    CODE = 131              # CODE a$: pops the string; HL = its first byte, or 0 if it's empty


NAME = {v: k for k, v in vars(RT).items() if not k.startswith("_")}
