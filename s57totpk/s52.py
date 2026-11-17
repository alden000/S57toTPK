"""S-52-style presentation rules, evaluated once per feature in Python.

The composite step stores the result as a handful of short derived properties
on every feature, so the MapLibre style (web/style.js) can stay generic:

  _fill  area fill colour token           _p    draw priority (sort key)
  _lc    line colour token                _lw   line width (CSS px)
  _ld    line dash: s solid, d dash, o dot, l long dash
  _sym   point symbol key (drawn on the device by web/symbols.js)
  _rot   symbol rotation (deg), _sa symbol anchor offset class
  _txt   label text, _tc text colour token, _tf font (R/I/B), _tz label min zoom
  _snd/_sndf/_sndc  sounding integer part / tenths / colour token
  _mz    minimum (256-px tile) zoom from SCAMIN

Colour tokens are the S-52 colour names; their RGB per colour scheme is in
COLOURS below and is sent to the page at render time.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, asdict

# ---------------------------------------------------------------- colours --
_DAY = {
    "NODTA": (163, 180, 183), "CHBLK": (7, 7, 7), "CHGRD": (125, 137, 140),
    "CHGRF": (163, 180, 183), "CHRED": (241, 84, 105), "CHGRN": (104, 228, 86),
    "CHYLW": (244, 218, 72), "CHMGD": (197, 69, 195), "CHMGF": (211, 166, 233),
    "CHBRN": (177, 145, 57), "CHWHT": (212, 234, 238), "CHCOR": (235, 125, 54),
    "LITRD": (241, 84, 105), "LITGN": (104, 228, 86), "LITYW": (244, 218, 72),
    "ISDNG": (197, 69, 195), "DNGHL": (241, 84, 105), "TRFCD": (197, 69, 195),
    "TRFCF": (211, 166, 233), "LANDA": (201, 185, 122), "LANDF": (139, 102, 31),
    "CSTLN": (82, 90, 92), "SNDG1": (125, 137, 140), "SNDG2": (7, 7, 7),
    "DEPSC": (82, 90, 92), "DEPCN": (125, 137, 140), "DEPDW": (212, 234, 238),
    "DEPMD": (186, 213, 225), "DEPMS": (152, 197, 242), "DEPVS": (115, 182, 239),
    "DEPIT": (131, 178, 149), "RESBL": (58, 120, 240), "ADINF": (178, 159, 52),
    "RESGR": (125, 137, 140), "OUTLW": (7, 7, 7), "OUTLL": (201, 185, 122),
    "BKAJ1": (7, 7, 7), "BKAJ2": (35, 39, 40), "WHITE": (255, 255, 255),
}
_DUSK = {
    "NODTA": (65, 72, 73), "CHBLK": (163, 180, 183), "CHGRD": (125, 137, 140),
    "CHGRF": (65, 72, 73), "CHRED": (159, 31, 52), "CHGRN": (34, 121, 23),
    "CHYLW": (135, 117, 23), "CHMGD": (159, 68, 157), "CHMGF": (79, 42, 92),
    "CHBRN": (66, 54, 21), "CHWHT": (163, 180, 183), "CHCOR": (178, 77, 2),
    "LITRD": (159, 31, 52), "LITGN": (34, 121, 23), "LITYW": (135, 117, 23),
    "ISDNG": (159, 68, 157), "DNGHL": (159, 31, 52), "TRFCD": (159, 68, 157),
    "TRFCF": (79, 42, 92), "LANDA": (52, 47, 31), "LANDF": (95, 69, 21),
    "CSTLN": (125, 137, 140), "SNDG1": (82, 90, 92), "SNDG2": (163, 180, 183),
    "DEPSC": (125, 137, 140), "DEPCN": (82, 90, 92), "DEPDW": (7, 7, 7),
    "DEPMD": (23, 30, 36), "DEPMS": (30, 46, 70), "DEPVS": (43, 64, 104),
    "DEPIT": (44, 60, 50), "RESBL": (58, 120, 240), "ADINF": (88, 79, 26),
    "RESGR": (82, 90, 92), "OUTLW": (7, 7, 7), "OUTLL": (52, 47, 31),
    "BKAJ1": (7, 7, 7), "BKAJ2": (23, 26, 27), "WHITE": (200, 200, 200),
}
_NIGHT = {
    "NODTA": (30, 33, 34), "CHBLK": (82, 90, 92), "CHGRD": (65, 72, 73),
    "CHGRF": (30, 33, 34), "CHRED": (82, 16, 26), "CHGRN": (17, 60, 12),
    "CHYLW": (66, 58, 12), "CHMGD": (80, 34, 79), "CHMGF": (40, 21, 46),
    "CHBRN": (33, 27, 10), "CHWHT": (82, 90, 92), "CHCOR": (89, 38, 1),
    "LITRD": (82, 16, 26), "LITGN": (17, 60, 12), "LITYW": (66, 58, 12),
    "ISDNG": (80, 34, 79), "DNGHL": (82, 16, 26), "TRFCD": (80, 34, 79),
    "TRFCF": (40, 21, 46), "LANDA": (26, 23, 15), "LANDF": (48, 35, 10),
    "CSTLN": (65, 72, 73), "SNDG1": (41, 45, 46), "SNDG2": (82, 90, 92),
    "DEPSC": (65, 72, 73), "DEPCN": (41, 45, 46), "DEPDW": (0, 0, 0),
    "DEPMD": (7, 9, 12), "DEPMS": (11, 17, 26), "DEPVS": (16, 25, 40),
    "DEPIT": (18, 26, 21), "RESBL": (29, 60, 120), "ADINF": (44, 40, 13),
    "RESGR": (41, 45, 46), "OUTLW": (0, 0, 0), "OUTLL": (26, 23, 15),
    "BKAJ1": (0, 0, 0), "BKAJ2": (11, 12, 13), "WHITE": (100, 100, 100),
}
COLOURS = {"day": _DAY, "dusk": _DUSK, "night": _NIGHT}
SCHEMES = tuple(COLOURS)


def palette_hex(scheme: str) -> dict[str, str]:
    return {k: "#%02x%02x%02x" % v for k, v in COLOURS[scheme].items()}


# ------------------------------------------------------------- parameters --
@dataclass
class S52Params:
    safety_depth: float = 10.0       # soundings / isolated dangers
    shallow_contour: float = 2.0
    safety_contour: float = 10.0
    deep_contour: float = 30.0
    two_shades: bool = False
    labels: bool = True

    def to_dict(self):
        return asdict(self)


# ---------------------------------------------------------------- helpers --
def _f(v, default=None):
    if v is None or v == "":
        return default
    try:
        x = float(v)
    except (TypeError, ValueError):
        return default
    return default if math.isnan(x) else x


def _i(v, default=None):
    x = _f(v)
    return default if x is None else int(x)


def _list(v) -> list[int]:
    if v is None or v == "":
        return []
    out = []
    for s in str(v).split(","):
        s = s.strip()
        if s:
            try:
                out.append(int(float(s)))
            except ValueError:
                pass
    return out


WORLD_SCALE_Z0 = 591657527.591555  # ArcGIS/Google LOD 0 scale at 96 dpi


def scamin_to_zoom(scamin, lat: float) -> int | None:
    """Smallest 256-px tile zoom at which a feature with SCAMIN shows."""
    s = _f(scamin)
    if not s or s <= 0:
        return None
    c = max(math.cos(math.radians(lat)), 0.05)
    z = math.log2(WORLD_SCALE_Z0 * c / s)
    return max(0, math.ceil(z - 1e-6))


# ------------------------------------------------------------------ tables --
# area fills: OBJL -> (token, priority)
AREA_FILL = {
    "UNSARE": ("NODTA", 3), "LNDARE": ("LANDA", 4), "BUAARE": ("CHBRN", 5),
    "LAKARE": ("DEPVS", 5), "RIVERS": ("DEPVS", 5), "CANALS": ("DEPVS", 5),
    "DOCARE": ("DEPVS", 5), "LOKBSN": ("DEPVS", 5), "DRYDOC": ("CHBRN", 6),
    "FLODOC": ("CHBRN", 6), "PONTON": ("CHBRN", 6), "HULKES": ("CHBRN", 6),
    "SLCONS": ("CHGRF", 6), "CAUSWY": ("CHGRF", 6), "DAMCON": ("CHBRN", 6),
    "MORFAC": ("CHBRN", 6), "SILTNK": ("CHBRN", 7), "BUISGL": ("CHBRN", 7),
    "BRIDGE": ("CHGRF", 7), "RUNWAY": ("CHGRF", 6), "PYLONS": ("CHGRD", 7),
    "TSEZNE": ("TRFCF", 8), "OFSPLF": ("CHBRN", 7), "ICEARE": ("CHWHT", 5),
}
# area boundary lines: OBJL -> (token, width, dash)
AREA_LINE = {
    "DRGARE": ("CHGRF", 1.0, "d"), "LAKARE": ("CSTLN", 0.8, "s"),
    "DRYDOC": ("CSTLN", 1.2, "s"), "FLODOC": ("CSTLN", 1.2, "s"),
    "PONTON": ("CSTLN", 1.2, "s"), "HULKES": ("CSTLN", 1.2, "s"),
    "SLCONS": ("CSTLN", 1.5, "s"), "CAUSWY": ("CSTLN", 1.2, "s"),
    "DAMCON": ("CSTLN", 1.2, "s"), "MORFAC": ("CSTLN", 1.0, "s"),
    "SILTNK": ("CSTLN", 1.0, "s"), "BUISGL": ("CSTLN", 1.0, "s"),
    "BRIDGE": ("CHGRD", 1.2, "s"), "OFSPLF": ("CSTLN", 1.0, "s"),
    "BERTHS": ("CHGRD", 0.8, "d"), "GATCON": ("CSTLN", 1.2, "s"),
    "RESARE": ("CHMGD", 1.2, "d"), "CTNARE": ("CHMGD", 1.2, "d"),
    "ACHARE": ("CHMGF", 1.2, "d"), "ACHBRT": ("CHMGF", 1.0, "d"),
    "MIPARE": ("CHMGD", 1.2, "d"), "CBLARE": ("CHMGD", 1.2, "d"),
    "PIPARE": ("CHMGD", 1.2, "d"), "DMPGRD": ("CHGRD", 1.0, "d"),
    "FAIRWY": ("CHGRF", 1.0, "d"), "DWRTPT": ("TRFCD", 1.2, "d"),
    "PRCARE": ("TRFCD", 1.2, "d"), "MARCUL": ("CHGRD", 1.0, "d"),
    "FSHFAC": ("CHGRD", 1.0, "d"), "SPLARE": ("CHMGD", 1.0, "d"),
    "ISTZNE": ("TRFCD", 1.2, "d"), "TSSRON": ("TRFCD", 1.2, "d"),
    "TSSCRS": ("TRFCD", 1.2, "d"), "SUBTLN": ("CHMGD", 1.0, "d"),
    "PILBOP": ("CHMGD", 1.0, "d"), "LOGPON": ("CHGRD", 1.0, "d"),
    "CTSARE": ("CHMGD", 1.0, "d"), "OSPARE": ("CHMGD", 1.0, "d"),
    "PRDARE": ("CHBLK", 0.8, "d"), "HRBBSN": ("CHGRD", 0.8, "d"),
    "TESARE": ("CHGRF", 1.0, "l"), "RUNWAY": ("CHGRD", 0.8, "s"),
}
# symbol at an area's representative point
AREA_SYMBOL = {
    "RESARE": "resare", "CTNARE": "ctnare", "ACHARE": "achare", "ACHBRT": "achare",
    "MIPARE": "mipare", "CBLARE": "cblare", "PIPARE": "pipare", "DMPGRD": "dmpgrd",
    "MARCUL": "marcul", "FSHFAC": "fshfac", "PILBOP": "pilbop", "TSSLPT": "tsslpt",
    "DWRTPT": "tsslpt", "SPLARE": "ctnare", "OSPARE": "ctnare", "CTSARE": "ctnare",
}
# line objects: OBJL -> (token, width, dash, priority)
LINE = {
    "COALNE": ("CSTLN", 1.6, "s", 20), "SLCONS": ("CSTLN", 1.6, "s", 20),
    "LNDARE": ("CSTLN", 1.2, "s", 19), "NAVLNE": ("CHGRD", 1.0, "d", 14),
    "RECTRC": ("CHBLK", 1.4, "s", 14), "DWRTCL": ("TRFCD", 1.4, "d", 14),
    "TSELNE": ("TRFCF", 4.0, "s", 13), "TSSBND": ("TRFCD", 2.0, "d", 13),
    "CBLSUB": ("CHMGD", 1.0, "d", 12), "CBLOHD": ("CHGRD", 1.2, "d", 15),
    "PIPSOL": ("CHGRD", 1.0, "l", 12), "PIPOHD": ("CHGRD", 1.5, "s", 15),
    "BRIDGE": ("CHGRD", 2.0, "s", 18), "ROADWY": ("CHBLK", 0.9, "s", 16),
    "RAILWY": ("CHBLK", 1.2, "d", 16), "RIVERS": ("CHGRD", 1.0, "s", 16),
    "CANALS": ("CHGRD", 1.0, "s", 16), "LNDELV": ("LANDF", 0.8, "s", 15),
    "FNCLNE": ("CSTLN", 1.0, "s", 16), "CONVYR": ("CHGRD", 1.0, "d", 16),
    "DYKCON": ("CSTLN", 1.5, "s", 18), "DAMCON": ("CSTLN", 1.5, "s", 18),
    "GATCON": ("CSTLN", 1.5, "s", 18), "PONTON": ("CSTLN", 1.5, "s", 18),
    "HULKES": ("CSTLN", 1.5, "s", 18), "FLODOC": ("CSTLN", 1.5, "s", 18),
    "MORFAC": ("CSTLN", 1.5, "s", 18), "BERTHS": ("CHGRD", 1.0, "s", 16),
    "OBSTRN": ("CHBLK", 1.2, "o", 17), "SLOTOP": ("CSTLN", 0.8, "s", 15),
    "CAUSWY": ("CSTLN", 2.0, "s", 18), "TUNNEL": ("CHGRD", 1.0, "d", 15),
    "MARCUL": ("CHGRD", 1.0, "d", 12), "FERYRT": ("CHMGD", 1.0, "d", 12),
    "RADLNE": ("TRFCD", 1.0, "d", 12), "STSLNE": ("CHGRF", 1.0, "l", 11),
    "FSHFAC": ("CHGRD", 1.0, "d", 12), "WATFAL": ("CHGRD", 1.0, "s", 15),
    "DEPCNT": ("DEPCN", 0.7, "s", 10),
}
BUOYS = {"BOYLAT", "BOYCAR", "BOYISD", "BOYSAW", "BOYSPP", "BOYINB"}
BEACONS = {"BCNLAT", "BCNCAR", "BCNISD", "BCNSAW", "BCNSPP"}
POINT_SYMBOL = {
    "LITFLT": "litves", "LITVES": "litves", "DAYMAR": "daymar", "FOGSIG": "fogsig",
    "RTPBCN": "radio", "RDOSTA": "radio", "RADSTA": "radio", "SILTNK": "tank",
    "PILPNT": "pile", "MORFAC": "morfac", "ACHBRT": "achare", "ACHARE": "achare",
    "PILBOP": "pilbop", "CGUSTA": "stn", "RSCSTA": "stn", "SISTAT": "stn",
    "SISTAW": "stn", "RDOCAL": "stn", "CRANES": "crane", "OFSPLF": "ofsplf",
    "PYLONS": "pylon", "RESARE": "resare", "CTNARE": "ctnare", "MARCUL": "marcul",
    "FSHFAC": "fshfac", "SMCFAC": "smcfac", "HRBFAC": "hrbfac", "SPRING": "spring",
    "DMPGRD": "dmpgrd", "MIPARE": "mipare", "CURENT": "curent", "TS_FEB": "curent",
}
# named areas that get an italic name label
AREA_NAMES = {"SEAARE", "LNDRGN", "BUAARE", "HRBARE", "ADMARE", "ACHARE",
              "FAIRWY", "RESARE", "DOCARE", "LAKARE", "RIVERS", "CANALS",
              "DMPGRD", "CTNARE", "ISTZNE", "PRCARE", "MIPARE", "SNDWAV"}
SKIN_OF_EARTH = ("DEPARE", "DRGARE", "LNDARE", "UNSARE")

LITCHR = {1: "F", 2: "Fl", 3: "LFl", 4: "Q", 5: "VQ", 6: "UQ", 7: "Iso", 8: "Oc",
          9: "IQ", 10: "IVQ", 11: "IUQ", 12: "Mo", 13: "FFl", 14: "Fl+LFl",
          15: "Oc+Fl", 16: "FLFl", 17: "Al.Oc", 18: "Al.LFl", 19: "Al.Fl",
          20: "Al.Gr", 25: "Q+LFl", 26: "VQ+LFl", 27: "UQ+LFl", 28: "Al",
          29: "Al.FFl"}
LITCOL = {1: "W", 3: "R", 4: "G", 5: "Bu", 6: "Y", 9: "Am", 10: "Vi", 11: "Or",
          12: "Mg", 13: "Pk"}
NATSUR = {1: "M", 2: "Cy", 3: "Si", 4: "S", 5: "St", 6: "G", 7: "P", 8: "Cb",
          9: "R", 11: "La", 14: "Co", 17: "Sh", 18: "Bo"}
NATQUA = {1: "f", 2: "m", 3: "c", 4: "bk", 5: "sy", 6: "so", 7: "sf", 8: "v",
          9: "ca", 10: "h"}

_SHORT_NAME = re.compile(
    r"(?:Buoy|Beacon|Daybeacon|Light|Bell|Whistle|Gong|Horn|Mark)\s+([A-Za-z0-9\"\-]{1,6})$")


def short_name(name: str | None) -> str | None:
    """Paper-chart style name for aids to navigation: '"2"' from
    'Point Judith Light 2'; short names pass through; long ones are dropped."""
    if not name:
        return None
    name = name.strip()
    m = _SHORT_NAME.search(name)
    if m:
        return '"%s"' % m.group(1).strip('"')
    return name if len(name) <= 20 else None


def light_colour_token(colours: list[int]) -> str:
    if not colours:
        return "LITYW"
    c = colours[0]
    if len(colours) > 1 and set(colours[:2]) == {3, 4}:
        return "LITYW"
    return {3: "LITRD", 4: "LITGN"}.get(c, "LITYW")


def light_description(a: dict) -> str:
    chr_ = LITCHR.get(_i(a.get("LITCHR"), 0), "")
    grp = (a.get("SIGGRP") or "").strip()
    if grp in ("()", "(1)"):
        grp = ""
    cols = "".join(LITCOL.get(c, "") for c in _list(a.get("COLOUR")))
    s = f"{chr_}{grp}{cols}"
    per = _f(a.get("SIGPER"))
    if per:
        s += f" {per:g}s"
    h = _f(a.get("HEIGHT"))
    if h:
        s += f" {h:g}m"
    r = _f(a.get("VALNMR"))
    if r:
        s += f" {r:g}M"
    return s.strip()


def sounding_props(depth: float, p: S52Params) -> dict:
    d = abs(depth)
    if d < 31 and abs(d - round(d)) >= 0.05:
        whole = int(math.floor(d + 1e-9))
        frac = str(int(round((d - whole) * 10)) % 10)
        if frac == "0":
            frac = ""
    else:
        whole, frac = int(math.floor(d + 1e-9)), ""
    out = {"_snd": str(whole), "_sndc": "SNDG2" if depth <= p.safety_depth else "SNDG1"}
    if frac:
        out["_sndf"] = frac
    if depth < 0:
        out["_sndd"] = 1  # drying height
    return out


def depth_fill(drval1, drval2, p: S52Params) -> str:
    d1 = _f(drval1, -1.0)
    d2 = _f(drval2, d1 + 0.01)
    if d1 < 0 and d2 <= 0:
        return "DEPIT"
    if p.two_shades:
        return "DEPDW" if d1 >= p.safety_contour and d2 > p.safety_contour else "DEPVS"
    tok = "DEPVS"
    if d1 >= p.shallow_contour and d2 > p.shallow_contour:
        tok = "DEPMS"
    if d1 >= p.safety_contour and d2 > p.safety_contour:
        tok = "DEPMD"
    if d1 >= p.deep_contour and d2 > p.deep_contour:
        tok = "DEPDW"
    return tok


def _danger(a: dict, p: S52Params) -> bool:
    v = _f(a.get("VALSOU"))
    return v is not None and v <= p.safety_depth


def _seabed_text(a: dict) -> str | None:
    sur = [NATSUR.get(x) for x in _list(a.get("NATSUR"))]
    qua = [NATQUA.get(x) for x in _list(a.get("NATQUA"))]
    parts = []
    for i, s in enumerate(sur):
        if not s:
            continue
        q = qua[i] if i < len(qua) and qua[i] else ""
        parts.append(q + s)
    return ".".join(parts) or None


# ---------------------------------------------------------------- classify --
def classify(objl: str, a: dict, gtype: str, p: S52Params, safety_valdco=None) -> dict | None:
    """Derived properties for one feature. gtype: 'P', 'L' or 'A'.
    Returns None when the feature is not drawn at all."""
    out: dict = {}

    if gtype == "A":
        if objl in ("DEPARE", "DRGARE"):
            out["_fill"] = depth_fill(a.get("DRVAL1"), a.get("DRVAL2"), p)
            out["_p"] = 1 if objl == "DEPARE" else 2
        elif objl in AREA_FILL:
            out["_fill"], out["_p"] = AREA_FILL[objl]
        elif objl in ("OBSTRN", "WRECKS", "UWTROC"):
            wl = _i(a.get("WATLEV"))
            if wl in (1, 2):
                out["_fill"], out["_p"] = "CHBRN", 7
                out["_lc"], out["_lw"], out["_ld"] = "CSTLN", 1.0, "s"
            else:
                if _danger(a, p):
                    out["_fill"], out["_p"] = "DEPVS", 7
                out["_lc"] = "CHBLK" if _danger(a, p) or wl in (4, 5) else "CHGRD"
                out["_lw"], out["_ld"] = 1.2, "o"
        if objl in AREA_LINE:
            out["_lc"], out["_lw"], out["_ld"] = AREA_LINE[objl]
        if objl == "TSEZNE":
            out["_op"] = 0.3
        return out or None

    if gtype == "L":
        if objl in LINE:
            tok, w, d, pr = LINE[objl]
            out.update(_lc=tok, _lw=w, _ld=d, _p=pr)
            if objl == "DEPCNT":
                v = _f(a.get("VALDCO"))
                if v is not None:
                    out["_txt"] = f"{v:g}"
                    out["_tc"] = "DEPCN"
                if safety_valdco is not None and v is not None and abs(v - safety_valdco) < 1e-6:
                    out.update(_lc="DEPSC", _lw=2.0, _p=11, _safc=1)
            elif objl == "RECTRC" and _i(a.get("CATTRK")) == 2:
                out["_ld"] = "d"
            elif objl == "PIPSOL" and set(_list(a.get("CATPIP"))) & {2, 3}:
                out["_lc"] = "CHMGD"
            elif objl == "NAVLNE" and a.get("ORIENT"):
                out["_txt"] = f"{_f(a.get('ORIENT')):05.1f}°"
                out["_tc"] = "CHBLK"
            return out
        return None

    # points ------------------------------------------------------------
    name = a.get("OBJNAM")
    if objl == "SOUNDG":
        d = _f(a.get("DEPTH"))
        return sounding_props(d, p) if d is not None else None
    if objl in BUOYS:
        shp = _i(a.get("BOYSHP"), 0)
        out["_sym"] = f"boy|{shp}|{a.get('COLOUR') or ''}|{a.get('COLPAT') or ''}"
        out["_p"] = 30
        if p.labels:
            sn = short_name(name)
            if sn:
                out.update(_txt=sn, _tc="CHBLK", _tf="R", _tz=13)
        return out
    if objl in BEACONS:
        shp = _i(a.get("BCNSHP"), 0)
        out["_sym"] = f"bcn|{shp}|{a.get('COLOUR') or ''}|{a.get('COLPAT') or ''}"
        out["_p"] = 30
        if p.labels:
            sn = short_name(name)
            if sn:
                out.update(_txt=sn, _tc="CHBLK", _tf="R", _tz=13)
        return out
    if objl == "TOPMAR":
        out["_sym"] = f"top|{_i(a.get('TOPSHP'), 0)}|{a.get('COLOUR') or ''}"
        out["_p"] = 31
        out["_sa"] = 1  # sits on top of the buoy/beacon symbol
        return out
    if objl == "LIGHTS":
        cols = _list(a.get("COLOUR"))
        tok = light_colour_token(cols)
        s1, s2 = _f(a.get("SECTR1")), _f(a.get("SECTR2"))
        catlit = set(_list(a.get("CATLIT")))
        if s1 is not None and s2 is not None:
            rng = _f(a.get("VALNMR"), 0) or 0
            big = 1 if rng >= 10 else 0
            out["_sym"] = f"lts|{s1:g}|{s2:g}|{tok}|{big}"
            out["_p"] = 32
        elif catlit & {1, 16}:  # directional / leading lights: plain flare
            out["_sym"] = f"lt|{tok}"
            out["_p"] = 32
            or_ = _f(a.get("ORIENT"))
            if or_ is not None:
                out["_rot"] = (or_ + 180) % 360
        else:
            out["_sym"] = f"lt|{tok}"
            out["_p"] = 32
        if p.labels:
            desc = light_description(a)
            if desc:
                out.update(_txt=desc, _tc="CHBLK", _tf="R", _tz=12)
        return out
    if objl == "LNDMRK":
        out["_sym"] = f"lmk|{(_list(a.get('CATLMK')) or [0])[0]}|{1 if _i(a.get('CONVIS')) == 1 else 0}"
        out["_p"] = 25
        if p.labels and name and _i(a.get("CONVIS")) == 1 and len(name) <= 24:
            out.update(_txt=name, _tc="CHBLK", _tf="R", _tz=13)
        return out
    if objl == "BUISGL":
        out["_sym"] = f"bui|{1 if _i(a.get('CONVIS')) == 1 else 0}"
        out["_p"] = 24
        return out
    if objl in ("WRECKS", "UWTROC", "OBSTRN"):
        wl = _i(a.get("WATLEV"))
        v = _f(a.get("VALSOU"))
        under = _f(a.get("_under"))
        isolated = under is None or under >= p.safety_contour
        if _danger(a, p) and wl not in (1, 2) and isolated:
            out["_sym"] = "isodgr"
        elif objl == "WRECKS":
            cw = _i(a.get("CATWRK"))
            if wl in (1, 2) or cw == 5:
                out["_sym"] = "wrk|hull"
            elif cw == 4:
                out["_sym"] = "wrk|mast"
            elif cw == 1 or (v is not None and v > p.safety_depth):
                out["_sym"] = "wrk|nd"
            else:
                out["_sym"] = "wrk|d"
        elif objl == "UWTROC":
            out["_sym"] = {4: "rock|cov", 5: "rock|awash"}.get(wl, "rock|uw")
        else:
            cat = _i(a.get("CATOBS"))
            out["_sym"] = "obstn|foul" if cat == 6 else "obstn"
        if v is not None and out["_sym"] in ("isodgr", "obstn", "wrk|nd", "wrk|d"):
            out.update(sounding_props(v, p))
        out["_p"] = 28
        return out
    if objl == "SBDARE":
        t = _seabed_text(a)
        return {"_txt": t, "_tc": "CHGRD", "_tf": "I", "_tz": 13, "_p": 5} if t else None
    if objl == "LNDELV":
        e = _f(a.get("ELEVAT"))
        out = {"_sym": "elev", "_p": 15}
        if e is not None:
            out.update(_txt=f"{e:g}", _tc="CHBLK", _tf="R", _tz=13)
        return out
    if objl in ("SEAARE", "LNDRGN"):
        if p.labels and name:
            return {"_txt": name, "_tc": "CHBLK" if objl == "SEAARE" else "CHGRD", "_tf": "I", "_tz": 11, "_p": 4}
        return None
    if objl in POINT_SYMBOL:
        out["_sym"] = POINT_SYMBOL[objl]
        out["_p"] = 26
        if objl in ("CURENT", "TS_FEB") and a.get("ORIENT"):
            out["_rot"] = _f(a.get("ORIENT"))
        if p.labels and objl in ("PILBOP", "SMCFAC", "HRBFAC") and name and len(name) <= 24:
            out.update(_txt=name, _tc="CHBLK", _tf="R", _tz=14)
        return out
    return None


def area_point(objl: str, a: dict, p: S52Params) -> dict | None:
    """Properties of the companion point drawn at an area's representative
    point (centred symbol and/or name label)."""
    out = {}
    if objl in AREA_SYMBOL:
        out["_sym"] = AREA_SYMBOL[objl]
        out["_p"] = 22
        if objl in ("TSSLPT", "DWRTPT") and _f(a.get("ORIENT")) is not None:
            out["_rot"] = _f(a.get("ORIENT"))
    if objl == "SBDARE":
        t = _seabed_text(a)
        if t:
            out.update(_txt=t, _tc="CHGRD", _tf="I", _tz=13, _p=5)
    elif p.labels and objl in AREA_NAMES and a.get("OBJNAM"):
        tc = "CHMGD" if objl in ("RESARE", "ACHARE", "CTNARE", "MIPARE") else "CHBLK"
        if objl in ("LNDRGN", "BUAARE"):
            tc = "CHGRD"
        out.update(_txt=a["OBJNAM"].strip(), _tc=tc, _tf="I",
                   _tz=10 if objl == "SEAARE" else 12)
        out.setdefault("_p", 4)
    return out or None
