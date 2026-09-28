"""TAP files and BASIC program bytes (plain Python, no emulator).

    blocks = tap_blocks(data)                 # payloads: flag + data + checksum
    name, prog = program_of_tap(data)         # the first BASIC program on a tape
    lines = split_lines(prog); prog = join_lines(lines)
    tap = program_tap(name, loader(clear, usr), autostart=10) + code_tap('code', start, code)
"""
import struct


def tap_blocks(data):
    """TAP bytes -> the list of block payloads (flag + data + checksum)."""
    out, i = [], 0
    while i + 2 <= len(data):
        n = data[i] | data[i + 1] << 8
        out.append(bytes(data[i + 2:i + 2 + n]))
        i += 2 + n
    return out


def tap_block(flag, payload):
    body = bytes([flag]) + payload
    ck = 0
    for b in body:
        ck ^= b
    body += bytes([ck])
    return struct.pack('<H', len(body)) + body


def header(kind, name, length, p1, p2):
    """kind 0 = program (p1 = autostart line or 32768, p2 = program length
    without variables), 3 = bytes (p1 = start, p2 = 32768)."""
    name = name.encode('latin-1')[:10].ljust(10)
    return tap_block(0x00, bytes([kind]) + name + struct.pack('<HHH', length, p1, p2))


def program_tap(name, prog, autostart=None):
    """A BASIC program (line bytes, no variables) as a TAP."""
    auto = 0x8000 if autostart is None else autostart
    return header(0, name, len(prog), auto, len(prog)) + tap_block(0xFF, prog)


def code_tap(name, start, code):
    """A CODE block as a TAP, the way SAVE ... CODE writes it."""
    return header(3, name, len(code), start, 0x8000) + tap_block(0xFF, code)


def split_lines(prog):
    """Program bytes -> [(line number, body including the final 0x0D)]."""
    out, p = [], 0
    while p + 4 <= len(prog):
        num = prog[p] << 8 | prog[p + 1]
        ln = prog[p + 2] | prog[p + 3] << 8
        out.append((num, bytes(prog[p + 4:p + 4 + ln])))
        p += 4 + ln
    return out


def join_lines(lines):
    out = bytearray()
    for num, body in lines:
        out += bytes([num >> 8, num & 0xFF]) + struct.pack('<H', len(body)) + body
    return bytes(out)


def program_of_tap(data):
    """(name, program bytes) of the first BASIC program on a tape."""
    blocks = tap_blocks(data)
    for i, b in enumerate(blocks[:-1]):
        if len(b) == 19 and b[0] == 0 and b[1] == 0:
            name = b[2:12].decode('latin-1').rstrip()
            plen = b[16] | b[17] << 8        # length without variables
            return name, blocks[i + 1][1:-1][:plen]
    raise ValueError('no BASIC program on this tape')


def small_int(v):
    """A small integer's 5-byte form, as the ROM stores it after a number."""
    sign = 0xFF if v < 0 else 0
    v &= 0xFFFF
    return bytes([0, sign, v & 0xFF, v >> 8, 0])


def loader(clear, usr):
    """The BASIC loader in front of the code: 10 CLEAR n / 20 LOAD ""CODE /
    30 RANDOMIZE USR n."""
    def num(v):
        return str(v).encode() + b'\x0e' + small_int(v)
    return join_lines([
        (10, b'\xfd' + num(clear) + b'\x0d'),              # CLEAR
        (20, b'\xef""\xaf\x0d'),                             # LOAD ""CODE
        (30, b'\xf9\xc0' + num(usr) + b'\x0d'),             # RANDOMIZE USR
    ])
