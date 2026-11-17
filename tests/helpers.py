"""Test helpers: a minimal ISO 8211 writer for synthetic S-57 headers."""
import struct


def _record(fields, leader_id=b"D"):
    tags = list(fields)
    data = b"".join(fields[t] for t in tags)
    s_len, s_pos, s_tag = 3, 4, 4
    dirent = b""
    pos = 0
    for t in tags:
        dirent += t.encode() + b"%03d" % len(fields[t]) + b"%04d" % pos
        pos += len(fields[t])
    dirent += b"\x1e"
    base = 24 + len(dirent)
    reclen = base + len(data)
    leader = (b"%05d" % reclen + b" " + leader_id + b"     " + b"%05d" % base + b"   "
              + b"%d%d0%d" % (s_len, s_pos, s_tag))
    assert len(leader) == 24
    return leader + dirent + data


def s57_file(path, name="TESTCELL", edtn=1, updn=0, isdt="20250101", cscl=22000, expp=1):
    ddr = _record({"0000": b"dummy\x1e"}, leader_id=b"L")
    dsid = (b"\x0a" + struct.pack("<I", 1) + bytes([expp, 1]) + f"{name}\x1f{edtn}\x1f{updn}\x1f".encode()
            + b"20250101" + isdt.encode() + b"03.1" + b"\x01" + b"\x1f" + b"2.0\x1f" + b"\x01" + struct.pack("<H", 550)
            + b"\x1f\x1e")
    rec = {"0001": b"\x01\x00\x1e", "DSID": dsid}
    recs = ddr + _record(rec)
    if expp == 1:
        dspm = b"\x14" + struct.pack("<I", 1) + bytes([2, 16, 12]) + struct.pack("<I", cscl) + bytes([1, 1, 1, 1]) \
            + struct.pack("<II", 10_000_000, 10) + b"\x1f\x1e"
        recs += _record({"0001": b"\x02\x00\x1e", "DSPM": dspm})
    with open(path, "wb") as fh:
        fh.write(recs)
