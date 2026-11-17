from s57totpk import s52

P = s52.S52Params()


def test_depth_fill_four_shades():
    assert s52.depth_fill(-2, 0, P) == "DEPIT"
    assert s52.depth_fill(0, 2, P) == "DEPVS"
    assert s52.depth_fill(2, 5, P) == "DEPMS"
    assert s52.depth_fill(10, 20, P) == "DEPMD"
    assert s52.depth_fill(30, 50, P) == "DEPDW"
    assert s52.depth_fill(5, 10, s52.S52Params(two_shades=True)) == "DEPVS"


def test_soundings():
    assert s52.sounding_props(3.5, P) == {"_snd": "3", "_sndf": "5", "_sndc": "SNDG2"}
    assert s52.sounding_props(35.7, P) == {"_snd": "35", "_sndc": "SNDG1"}
    d = s52.sounding_props(-1.2, P)
    assert d["_snd"] == "1" and d["_sndf"] == "2" and d["_sndd"] == 1


def test_light_description():
    a = {"LITCHR": 2, "SIGGRP": "(2)", "COLOUR": "4", "SIGPER": 5.0, "HEIGHT": 10, "VALNMR": 5}
    assert s52.light_description(a) == "Fl(2)G 5s 10m 5M"
    assert s52.light_description({"LITCHR": 4, "SIGGRP": "()", "COLOUR": "3"}) == "QR"


def test_scamin_zoom():
    # 1:22000 at the equator is between z14 (36112) and z15 (18056) -> z15
    assert s52.scamin_to_zoom(22000, 0) == 15
    assert s52.scamin_to_zoom(None, 0) is None


def test_short_name():
    assert s52.short_name("Point Judith Light 2") == '"2"'
    assert s52.short_name("Short name") == "Short name"
    assert s52.short_name("A very long name of some navigation mark") is None


def test_isolated_danger_rule():
    deep = s52.classify("UWTROC", {"VALSOU": 3.0, "WATLEV": 3, "_under": 20}, "P", P)
    shallow = s52.classify("UWTROC", {"VALSOU": 3.0, "WATLEV": 3, "_under": 2}, "P", P)
    assert deep["_sym"] == "isodgr"
    assert shallow["_sym"] == "rock|uw"


def test_palettes_complete():
    keys = set(s52.COLOURS["day"])
    for s in s52.SCHEMES:
        assert set(s52.COLOURS[s]) == keys
