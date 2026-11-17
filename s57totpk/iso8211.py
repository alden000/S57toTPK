"""Minimal ISO 8211 reader: just enough to pull DSID/DSPM header fields out of
S-57 base cells (.000) and update files (.001, .002 ...).

GDAL reads the full cell; this exists so we can pick editions and validate the
update sequence *before* handing files to GDAL.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass

UT = 0x1F  # unit terminator
FT = 0x1E  # field terminator


@dataclass
class DatasetHeader:
    dsnm: str = ""
    edtn: int = 0
    updn: int = 0
    expp: int = 0          # 1 = new edition / base, 2 = revision (update)
    uadt: str = ""
    isdt: str = ""
    cscl: int = 0          # compilation scale (DSPM; base cells only)
    comf: int = 10_000_000
    somf: int = 10


def _records(data: bytes):
    pos = 0
    n = len(data)
    while pos + 24 <= n:
        try:
            reclen = int(data[pos:pos + 5])
        except ValueError:
            return
        if reclen <= 24 or pos + reclen > n:
            return
        leader = data[pos:pos + 24]
        base = int(leader[12:17])
        s_len = int(leader[20:21])
        s_pos = int(leader[21:22])
        s_tag = int(leader[23:24])
        ent = s_tag + s_len + s_pos
        fields = {}
        d = pos + 24
        while d < pos + base - 1 and data[d] != FT:
            tag = data[d:d + s_tag].decode("ascii", "replace")
            flen = int(data[d + s_tag:d + s_tag + s_len])
            fpos = int(data[d + s_tag + s_len:d + ent])
            start = pos + base + fpos
            fields[tag] = data[start:start + flen]
            d += ent
        yield leader, fields
        pos += reclen


def _text(buf: bytes, i: int):
    j = buf.index(UT, i) if UT in buf[i:] else len(buf)
    return buf[i:j].decode("latin-1").strip(), j + 1


def _int(s: str) -> int:
    try:
        return int(s.strip() or 0)
    except ValueError:
        return 0


def read_header(path: str, max_bytes: int = 65536) -> DatasetHeader:
    """Read DSID (and DSPM if present) from an S-57 file."""
    with open(path, "rb") as f:
        data = f.read(max_bytes)
    h = DatasetHeader()
    got_dsid = got_dspm = False
    for i, (leader, fields) in enumerate(_records(data)):
        if i == 0:
            continue  # DDR
        if "DSID" in fields:
            b = fields["DSID"]
            # RCNM b11, RCID b14, EXPP b11, INTU b11, DSNM A, EDTN A, UPDN A,
            # UADT A(8), ISDT A(8) ...
            h.expp = b[5]
            p = 7
            h.dsnm, p = _text(b, p)
            e, p = _text(b, p)
            u, p = _text(b, p)
            h.edtn, h.updn = _int(e), _int(u)
            h.uadt = b[p:p + 8].decode("latin-1").strip()
            h.isdt = b[p + 8:p + 16].decode("latin-1").strip()
            got_dsid = True
        if "DSPM" in fields:
            b = fields["DSPM"]
            # RCNM b11, RCID b14, HDAT b11, VDAT b11, SDAT b11, CSCL b14,
            # DUNI b11, HUNI b11, PUNI b11, COUN b11, COMF b14, SOMF b14
            if len(b) >= 24:
                h.cscl = struct.unpack_from("<I", b, 8)[0]
                h.comf = struct.unpack_from("<I", b, 16)[0] or h.comf
                h.somf = struct.unpack_from("<I", b, 20)[0] or h.somf
            got_dspm = True
        if got_dsid and (got_dspm or i >= 3):
            break
    if not got_dsid:
        raise ValueError(f"{path}: no DSID record (not an S-57 file?)")
    return h
