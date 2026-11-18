"""Damaged (self-crossing) areas, as found in real ENC data, must not stop
the composite: GEOS raised 'TopologyException: side location conflict'."""
import shapely

from s57totpk.composite import Feature, _clip, _fill_slivers, _merge_split, _repair_area

BOW = shapely.Polygon([(103.60, 1.30), (103.70, 1.40), (103.70, 1.30), (103.60, 1.40), (103.60, 1.30)])
BOX = shapely.box(103.70, 1.30, 103.80, 1.40)


def _feats():
    a = {"DRVAL1": 5.0, "DRVAL2": 10.0}
    return [Feature("DEPARE", "A", BOW, dict(a), "C1", 22000), Feature("DEPARE", "A", BOX, dict(a), "C2", 22000)]


def test_bowtie_is_invalid_input():
    assert not BOW.is_valid


def test_repair_keeps_enclosed_area():
    g = _repair_area(BOW)
    assert g.is_valid and abs(g.area - 0.005) < 1e-9


def test_merge_split_survives_damaged_area():
    out = _merge_split(_feats(), log=lambda *_: None)
    assert sorted(round(f.geom.area, 6) for f in out) == [0.0025, 0.0125]   # right half joined the box


def test_fill_slivers_and_clip_survive_damaged_area():
    _fill_slivers(_feats(), shapely.box(103.6, 1.3, 103.8, 1.4), 200, log=lambda *_: None)
    assert len(_clip(_feats(), shapely.box(103.62, 1.3, 103.75, 1.4))) == 2
