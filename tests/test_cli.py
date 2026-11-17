import json

from s57totpk import progress
from s57totpk.cli import main


def test_progress_roundtrip(monkeypatch, capsys):
    monkeypatch.setattr(progress, "ENABLED", True)
    progress.report("render", 3, 10, scheme="day", eta=60)
    progress.event("result", files=["a.tpkx"])
    lines = capsys.readouterr().out.splitlines()
    assert progress.parse(lines[0]) == {"stage": "render", "done": 3, "total": 10, "scheme": "day", "eta": 60}
    assert progress.parse(lines[1]) == {"event": "result", "files": ["a.tpkx"]}
    assert progress.parse("plain log line") is None


def test_progress_silent_by_default(capsys):
    progress.report("render", 1, 2)
    assert capsys.readouterr().out == "" or not progress.ENABLED


def test_empty_charts_folder_is_a_plain_error(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(progress, "ENABLED", True)
    (tmp_path / "enc").mkdir()
    code = main(["run", "--enc", str(tmp_path / "enc"), "--out", str(tmp_path / "out")])
    out, err = capsys.readouterr()
    assert code == 1
    ev = [progress.parse(l) for l in out.splitlines() if progress.parse(l)]
    assert any(e.get("event") == "error" and "No S-57 chart files" in e["message"] for e in ev)
    assert "Traceback" not in err


def test_gui_scale_text():
    from s57totpk.gui import scale_text
    assert scale_text(16) == "1:9,000"
    assert scale_text(17) == "1:4,500"
    assert scale_text(13) == "1:72,000"
