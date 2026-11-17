import os

from s57totpk.cells import discover, stage
from s57totpk.iso8211 import read_header

from helpers import s57_file


def test_header_roundtrip(tmp_path):
    p = tmp_path / "AA5TEST1.000"
    s57_file(p, "AA5TEST1.000", edtn=7, updn=0, cscl=12000)
    h = read_header(str(p))
    assert (h.dsnm, h.edtn, h.updn, h.expp, h.cscl) == ("AA5TEST1.000", 7, 0, 1, 12000)


def test_highest_edition_and_update_sequence(tmp_path):
    a, b = tmp_path / "a" / "AA5TEST1", tmp_path / "b" / "AA5TEST1"
    a.mkdir(parents=True), b.mkdir(parents=True)
    s57_file(a / "AA5TEST1.000", edtn=2, isdt="20240101")
    s57_file(b / "AA5TEST1.000", edtn=3, updn=2, isdt="20250101")       # re-issue at update 2
    s57_file(a / "AA5TEST1.001", edtn=2, updn=1, expp=2)                 # old edition: ignored
    s57_file(a / "AA5TEST1.003", edtn=3, updn=3, expp=2, isdt="20250201")
    s57_file(b / "AA5TEST1.004", edtn=3, updn=4, expp=2, isdt="20250301")
    s57_file(b / "AA5TEST1.006", edtn=3, updn=6, expp=2, isdt="20250401")  # gap at 5
    cells = discover(str(tmp_path), log=lambda *_: None)
    assert len(cells) == 1
    c = cells[0]
    assert c.edition == 3 and c.base.startswith(str(b))
    assert [os.path.basename(u) for u in c.updates] == ["AA5TEST1.003", "AA5TEST1.004"]
    assert c.last_updn == 4 and c.warnings
    stage(cells, str(tmp_path / "work"))
    d = tmp_path / "work" / "AA5TEST1"
    assert sorted(os.listdir(d)) == ["AA5TEST1.000", "AA5TEST1.001", "AA5TEST1.002"]
    assert read_header(str(d / "AA5TEST1.001")).updn == 3


def test_cancelled_cell_dropped(tmp_path):
    s57_file(tmp_path / "AA5TEST2.000", edtn=4, isdt="20250101")
    s57_file(tmp_path / "AA5TEST2.001", edtn=0, updn=1, expp=2, isdt="20250301")
    assert discover(str(tmp_path), log=lambda *_: None) == []
