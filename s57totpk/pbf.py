"""Tiny protobuf writer (only what MVT and glyph PBFs need)."""
from __future__ import annotations

import struct


def varint(n: int) -> bytes:
    out = bytearray()
    n &= (1 << 64) - 1
    while True:
        b = n & 0x7F
        n >>= 7
        if n:
            out.append(b | 0x80)
        else:
            out.append(b)
            return bytes(out)


def zigzag(n: int) -> int:
    return (n << 1) ^ (n >> 63)


def key(field: int, wire: int) -> bytes:
    return varint((field << 3) | wire)


def f_varint(field: int, n: int) -> bytes:
    return key(field, 0) + varint(n)


def f_sint(field: int, n: int) -> bytes:
    return key(field, 0) + varint(zigzag(n))


def f_bytes(field: int, b: bytes) -> bytes:
    return key(field, 2) + varint(len(b)) + b


def f_str(field: int, s: str) -> bytes:
    return f_bytes(field, s.encode("utf-8"))


def f_double(field: int, x: float) -> bytes:
    return key(field, 1) + struct.pack("<d", x)


def f_packed(field: int, values) -> bytes:
    return f_bytes(field, b"".join(varint(v) for v in values))


# ------------------------------------------------------------------ reader --
def read_varint(buf: bytes, i: int):
    shift = n = 0
    while True:
        b = buf[i]
        i += 1
        n |= (b & 0x7F) << shift
        if not b & 0x80:
            return n, i
        shift += 7


def iter_fields(buf: bytes):
    """Yield (field, wire, value) — value is int for varint/fixed, bytes for
    length-delimited. Used by tests and the MBTiles inspector."""
    i = 0
    while i < len(buf):
        k, i = read_varint(buf, i)
        f, w = k >> 3, k & 7
        if w == 0:
            v, i = read_varint(buf, i)
        elif w == 1:
            v = struct.unpack_from("<d", buf, i)[0]
            i += 8
        elif w == 2:
            n, i = read_varint(buf, i)
            v = buf[i:i + n]
            i += n
        elif w == 5:
            v = struct.unpack_from("<f", buf, i)[0]
            i += 4
        else:
            raise ValueError(f"unsupported wire type {w}")
        yield f, w, v
