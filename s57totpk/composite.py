"""Read S-57 cells with GDAL and composite them by scale, like an ECDIS.

Largest-scale cell wins: each cell is kept only inside its own coverage
(M_COVR, CATCOV=1, minus CATCOV=2) less whatever larger-scale cells already
cover. Areas and lines split at cell edges are rejoined, and skin-of-earth
slivers between cells are filled from the neighbouring skin-of-earth area.

Output: one GeoJSONSeq file (EPSG:4326) with S-52 derived properties (see
s52.py) plus a small JSON metadata file.
"""
from __future__ import annotations

import json
import math
import os
import time
from collections import defaultdict
from dataclasses import dataclass

import numpy as np
import shapely

from . import progress, s52
from .cells import Cell, discover, stage

S57_OPTIONS = ("RETURN_PRIMITIVES=OFF,RETURN_LINKAGES=OFF,LNAM_REFS=OFF,"
               "UPDATES=APPLY,SPLIT_MULTIPOINT=ON,ADD_SOUNDG_DEPTH=ON")
GRID = 1e-7          # S-57 coordinate multiplication factor 10^7 -> exact grid
SKIP_LAYERS = {"DSID", "IsolatedNode", "ConnectedNode", "Edge", "Face",
               "C_AGGR", "C_ASSO", "C_STAC"}
DROP_ATTRS = {"RCID", "PRIM", "GRUP", "OBJL", "RVER", "AGEN", "FIDN", "FIDS",
              "RECDAT", "RECIND", "SORDAT", "SORIND", "LNAM", "LNAM_REFS",
              "FFPT_RIND", "NOBJNM", "NINFOM", "NTXTDS", "INFORM", "TXTDSC",
              "PICREP", "SCAMAX"}
# attributes copied to the output (besides derived ones); all others are
# dropped unless keep_all_attributes is set
KEEP_ATTRS = {"OBJNAM", "DRVAL1", "DRVAL2", "VALDCO", "VALSOU", "SCAMIN"}
MERGE_IGNORE = {"SCAMIN"}


@dataclass
class Feature:
    objl: str
    gtype: str            # 'P', 'L', 'A'
    geom: object          # shapely geometry, lon/lat
    attrs: dict
    cell: str
    scale: int


def _gtype(geom) -> str | None:
    t = shapely.get_type_id(geom)
    if t in (0, 4):
        return "P"
    if t in (1, 2, 5):
        return "L"
    if t in (3, 6):
        return "A"
    return None


def _clean(v):
    if v is None:
        return None
    if isinstance(v, (np.ndarray, list, tuple)):
        vals = [str(x) for x in v if x is not None and str(x) != ""]
        return ",".join(vals) if vals else None
    if isinstance(v, (float, np.floating)):
        if math.isnan(v):
            return None
        fv = float(v)
        return int(fv) if fv.is_integer() and abs(fv) < 2**31 else fv
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, bytes):
        v = v.decode("latin-1")
    if isinstance(v, str):
        v = v.strip()
        return v or None
    return v


# ------------------------------------------------------------- robustness --
# Real ENC data contains self-crossing or self-touching areas. GEOS overlay
# operations fail on those ("TopologyException: side location conflict"), so
# areas are repaired when read, and every overlay goes through _safe().
GEOSError = shapely.errors.GEOSException


def _make_valid(g):
    """Valid version of g (structure method keeps what the rings enclose)."""
    if g is None or g.is_empty or g.is_valid:
        return g
    try:
        return shapely.make_valid(g, method="structure", keep_collapsed=False)
    except (TypeError, ValueError, GEOSError):  # older GEOS / shapely
        return shapely.make_valid(g)


def _repair_area(g):
    g = _make_valid(g)
    return _keep_dim(g, "A") if g is not None and not g.is_empty else None


def _safe(fn, *geoms, **kw):
    """Run a GEOS overlay; on a topology error repair the inputs and retry,
    then retry without snapping to the grid."""
    try:
        return fn(*geoms, **kw)
    except GEOSError:
        pass
    fixed = [np.array([_make_valid(x) for x in g], dtype=object) if isinstance(g, np.ndarray) else _make_valid(g)
             for g in geoms]
    try:
        return fn(*fixed, **kw)
    except GEOSError:
        kw.pop("grid_size", None)
        return fn(*fixed, **kw)


def read_cell(path: str, cell: Cell, log=print) -> tuple[list[Feature], object]:
    import pyogrio
    from pyogrio.raw import read

    feats: list[Feature] = []
    cov_in, cov_out = [], []
    repaired = 0
    for name, _gt in pyogrio.list_layers(path):
        if name in SKIP_LAYERS or (name.startswith("M_") and name != "M_COVR"):
            continue
        try:
            meta, _fids, geoms, fields = read(path, layer=name)
        except Exception as e:  # noqa: BLE001
            log(f"  {cell.name}/{name}: read failed: {e}")
            continue
        if geoms is None or len(geoms) == 0:
            continue
        cols = list(meta["fields"])
        gs = shapely.force_2d(shapely.from_wkb(geoms))
        for i, g in enumerate(gs):
            if g is None or g.is_empty:
                continue
            attrs = {}
            for c, arr in zip(cols, fields):
                if c in DROP_ATTRS:
                    continue
                v = _clean(arr[i])
                if v is not None:
                    attrs[c] = v
            gt = _gtype(g)
            if gt == "A" and not g.is_valid:
                g = _repair_area(g)
                repaired += 1
                if g is None:
                    continue
            if name == "M_COVR":
                (cov_in if attrs.get("CATCOV", 1) == 1 else cov_out).append(g)
                continue
            if gt is None:
                continue
            feats.append(Feature(name, gt, g, attrs, cell.name, cell.scale))
    if repaired:
        log(f"  {cell.name}: repaired {repaired} damaged area shape(s)")
    if cov_in:
        cov = _safe(shapely.union_all, np.array(cov_in, dtype=object), grid_size=GRID)
        if cov_out:
            cov = _safe(shapely.difference, cov, _safe(shapely.union_all, np.array(cov_out, dtype=object), grid_size=GRID),
                        grid_size=GRID)
    else:  # no M_COVR: fall back to the extent of the data
        xs = shapely.bounds(np.array([f.geom for f in feats])) if feats else None
        cov = shapely.box(xs[:, 0].min(), xs[:, 1].min(), xs[:, 2].max(), xs[:, 3].max()) if feats else shapely.Polygon()
        log(f"  {cell.name}: no M_COVR, using data extent")
    return feats, cov


def _clip(feats: list[Feature], region) -> list[Feature]:
    if not feats:
        return []
    if region.is_empty:
        return []
    shapely.prepare(region)
    geoms = np.array([f.geom for f in feats], dtype=object)
    inside = shapely.contains(region, geoms)
    touch = shapely.intersects(region, geoms)
    out = []
    todo = np.where(touch & ~inside)[0]
    clipped = {}
    if len(todo):
        sub = geoms[todo]
        sub = np.array([_make_valid(g) for g in sub], dtype=object)
        try:
            res = shapely.intersection(sub, region, grid_size=GRID)
        except GEOSError:  # find the offending feature(s) one by one
            res = []
            for g in sub:
                try:
                    res.append(_safe(shapely.intersection, g, region, grid_size=GRID))
                except GEOSError:
                    res.append(g)  # keep it unclipped rather than lose it
        clipped = dict(zip(todo.tolist(), res))
    for i, f in enumerate(feats):
        if inside[i]:
            out.append(f)
        elif i in clipped:
            g = clipped[i]
            if g is None or g.is_empty:
                continue
            g = _keep_dim(g, f.gtype)
            if g is None:
                continue
            f.geom = g
            out.append(f)
    return out


def _keep_dim(g, gtype):
    """Drop lower-dimension leftovers from an intersection."""
    want = {"P": (0, 4), "L": (1, 5), "A": (3, 6)}[gtype]
    t = shapely.get_type_id(g)
    if t in want:
        return g
    if t == 7:  # collection
        parts = [p for p in shapely.get_parts(g) if shapely.get_type_id(p) in want + ((2,) if gtype == "L" else ())]
        if not parts:
            return None
        return _safe(shapely.union_all, np.array(parts, dtype=object)) if len(parts) > 1 else parts[0]
    if gtype == "L" and t == 2:
        return g
    return None


def _merge_key(f: Feature):
    return (f.objl, f.gtype, tuple(sorted((k, v) for k, v in f.attrs.items() if k not in MERGE_IGNORE)))


def _merge_split(feats: list[Feature], log=print) -> list[Feature]:
    """Rejoin areas/lines of identical class+attributes that come from more
    than one cell (i.e. were split at cell edges)."""
    groups: dict = defaultdict(list)
    keep = []
    for f in feats:
        if f.gtype in ("A", "L"):
            groups[_merge_key(f)].append(f)
        else:
            keep.append(f)
    merged_n = 0
    for _key, fs in groups.items():
        cells = {f.cell for f in fs}
        if len(fs) == 1 or len(cells) == 1:
            keep.extend(fs)
            continue
        geoms = np.array([f.geom for f in fs], dtype=object)
        try:
            if fs[0].gtype == "A":
                u = _safe(shapely.union_all, geoms, grid_size=GRID)
                parts = [p for p in shapely.get_parts(u) if shapely.get_type_id(p) == 3]
            else:
                u = shapely.line_merge(_safe(shapely.union_all, geoms, grid_size=GRID))
                parts = [p for p in shapely.get_parts(u) if shapely.get_type_id(p) in (1, 2)]
        except GEOSError as e:
            log(f"  could not rejoin {fs[0].objl} pieces ({e}); kept them separate")
            keep.extend(fs)
            continue
        scamins = [f.attrs.get("SCAMIN") for f in fs]
        scamin = None if any(s is None for s in scamins) else max(scamins)
        merged_n += len(fs) - len(parts)
        # assign each part the attributes of the member it overlaps most
        tree = shapely.STRtree(geoms)
        for part in parts:
            idx = tree.query(part, predicate="intersects")
            src = fs[int(idx[0])] if len(idx) else fs[0]
            attrs = dict(src.attrs)
            if scamin is None:
                attrs.pop("SCAMIN", None)
            else:
                attrs["SCAMIN"] = scamin
            keep.append(Feature(src.objl, src.gtype, part, attrs, src.cell,
                                min(f.scale for f in fs)))
    log(f"  rejoined split areas/lines: {merged_n} fewer pieces")
    return keep


def _dedupe_points(feats: list[Feature]) -> list[Feature]:
    seen = set()
    out = []
    for f in feats:
        if f.gtype == "P":
            k = (f.objl, shapely.to_wkb(f.geom), tuple(sorted(f.attrs.items())))
            if k in seen:
                continue
            seen.add(k)
        out.append(f)
    return out


def _fill_slivers(feats: list[Feature], covered, max_width_m: float, log=print) -> None:
    skin_idx = [i for i, f in enumerate(feats) if f.gtype == "A" and f.objl in s52.SKIN_OF_EARTH]
    if not skin_idx or covered.is_empty:
        return
    skin = np.array([feats[i].geom for i in skin_idx], dtype=object)
    try:
        skin_union = _safe(shapely.union_all, skin, grid_size=GRID)
        gaps = _safe(shapely.difference, covered, skin_union, grid_size=GRID)
    except GEOSError as e:
        log(f"  gaps between charts not filled ({e})")
        return
    parts = [g for g in shapely.get_parts(gaps) if shapely.get_type_id(g) == 3 and g.area > 0]
    if not parts:
        return
    tree = shapely.STRtree(skin)
    adds: dict[int, list] = defaultdict(list)
    filled = skipped = 0
    for g in parts:
        lat = g.centroid.y
        m_per_deg = 111_320.0 * math.sqrt(max(math.cos(math.radians(lat)), 0.05))
        half_width_m = (g.area / max(g.length, 1e-12)) * 2 * m_per_deg
        if half_width_m > max_width_m:
            skipped += 1
            continue
        cand = tree.query(g, predicate="intersects")
        if len(cand) == 0:
            cand = tree.query(g.buffer(GRID * 10), predicate="intersects")
        if len(cand) == 0:
            skipped += 1
            continue
        try:
            best = max(cand, key=lambda j: _safe(shapely.intersection, g.boundary, skin[j].buffer(GRID * 5)).length)
        except GEOSError:
            skipped += 1
            continue
        adds[int(best)].append(g)
        filled += 1
    for j, gs in adds.items():
        f = feats[skin_idx[j]]
        try:
            f.geom = _safe(shapely.union_all, np.array([f.geom] + gs, dtype=object), grid_size=GRID)
        except GEOSError:
            skipped += len(gs)
    log(f"  skin-of-earth slivers filled: {filled}" + (f" (left {skipped} wider gaps)" if skipped else ""))


def _tag_danger_depths(feats: list[Feature]) -> None:
    """Record DRVAL1 of the depth area under each point danger (S-52
    UDWHAZ: a danger is 'isolated' only in water deeper than the safety
    contour)."""
    areas = [f for f in feats if f.gtype == "A" and f.objl in ("DEPARE", "DRGARE", "LNDARE", "UNSARE")]
    pts = [f for f in feats if f.gtype == "P" and f.objl in ("WRECKS", "UWTROC", "OBSTRN")]
    if not areas or not pts:
        return
    tree = shapely.STRtree(np.array([a.geom for a in areas], dtype=object))
    pi, ai = tree.query(np.array([p.geom for p in pts], dtype=object), predicate="intersects")
    depth: dict[int, float] = {}
    for i, j in zip(pi.tolist(), ai.tolist()):
        a = areas[j]
        d = -1.0 if a.objl in ("LNDARE", "UNSARE") else float(a.attrs.get("DRVAL1", -1.0))
        depth[i] = min(depth.get(i, d), d)
    for i, p in enumerate(pts):
        if i in depth:
            p.attrs["_under"] = depth[i]


def _safety_valdco(cell_feats: list[Feature], p: s52.S52Params):
    vals = sorted({f.attrs["VALDCO"] for f in cell_feats if f.objl == "DEPCNT" and isinstance(f.attrs.get("VALDCO"), (int, float))})
    for v in vals:
        if v >= p.safety_contour:
            return v
    return None


def _props(f: Feature, derived: dict, keep_all: bool) -> dict:
    out = {"OBJL": f.objl}
    for k, v in f.attrs.items():
        if keep_all or k in KEEP_ATTRS:
            out[k] = v
    out.update(derived)
    out["_cs"] = f.scale
    return out


def build(enc_root: str, out_dir: str, params: s52.S52Params | None = None,
          sliver_max_width_m: float = 200.0, keep_all_attributes: bool = False,
          log=print) -> dict:
    import pyogrio

    params = params or s52.S52Params()
    t0 = time.time()
    os.makedirs(out_dir, exist_ok=True)
    pyogrio.set_gdal_config_options({"OGR_S57_OPTIONS": S57_OPTIONS})

    log(f"Scanning {enc_root}")
    cells = discover(enc_root, log=log)
    if not cells:
        raise SystemExit(f"No S-57 base cells (.000) found under {enc_root}")
    for c in cells:
        for w in c.warnings:
            log(f"  {c.name}: {w}")
    log(f"  {len(cells)} cells; staging updates")
    stage(cells, os.path.join(out_dir, "cells"))

    # largest scale (smallest denominator) first
    cells.sort(key=lambda c: (c.scale or 10**9, c.name))
    covered = shapely.Polygon()
    all_feats: list[Feature] = []
    safety_by_cell: dict = {}
    cell_info = []
    for n, c in enumerate(cells, 1):
        progress.report("composite", n - 1, len(cells), cell=c.name)
        feats, cov = read_cell(c.staged, c, log=log)
        eff = _safe(shapely.difference, cov, covered, grid_size=GRID) if not covered.is_empty else cov
        covered = _safe(shapely.union, covered, cov, grid_size=GRID)
        safety = _safety_valdco(feats, params)
        kept = _clip(feats, eff)
        safety_by_cell[c.name] = safety
        all_feats.extend(kept)
        cell_info.append({"name": c.name, "edition": c.edition, "update": c.last_updn,
                          "scale": c.scale, "features": len(kept), "issue": c.header.isdt})
        log(f"  [{n}/{len(cells)}] {c.name} 1:{c.scale:,} ed {c.edition} upd {c.last_updn}: "
            f"{len(kept)}/{len(feats)} features kept")

    progress.report("composite", len(cells), len(cells))
    all_feats = _dedupe_points(all_feats)
    all_feats = _merge_split(all_feats, log=log)
    _fill_slivers(all_feats, covered, sliver_max_width_m, log=log)
    _tag_danger_depths(all_feats)

    out_path = os.path.join(out_dir, "enc.geojsons")
    tmp = out_path + ".partial"
    counts = defaultdict(int)
    n_out = 0
    with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
        for f in all_feats:
            derived = s52.classify(f.objl, f.attrs, f.gtype, params, safety_by_cell.get(f.cell))
            g = f.geom
            if f.gtype == "A":
                g = shapely.orient_polygons(g) if hasattr(shapely, "orient_polygons") else g
            lat = shapely.get_y(shapely.point_on_surface(g)) if f.gtype != "P" else g.y
            mz = s52.scamin_to_zoom(f.attrs.get("SCAMIN"), lat)
            if derived is not None:
                if mz is not None:
                    derived["_mz"] = mz
                n_out += _write(fh, g, _props(f, derived, keep_all_attributes), mz)
                counts[f.objl] += 1
            if f.gtype == "A":
                ap = s52.area_point(f.objl, f.attrs, params)
                if ap:
                    if mz is not None:
                        ap["_mz"] = mz
                    ap["_ap"] = 1
                    n_out += _write(fh, shapely.point_on_surface(g), _props(f, ap, False), mz)
    os.replace(tmp, out_path)

    cov_simpl = shapely.simplify(covered, 1e-5)
    meta = {
        "created": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "source": os.path.abspath(enc_root),
        "signature": source_signature(enc_root),
        "bounds": list(covered.bounds),
        "coverage": json.loads(shapely.to_geojson(cov_simpl)),
        "cells": cell_info,
        "params": params.to_dict(),
        "features": n_out,
        "classes": dict(sorted(counts.items())),
    }
    with open(os.path.join(out_dir, "enc_meta.json"), "w", encoding="utf-8") as fh:
        json.dump(meta, fh, indent=1)
    log(f"Composite done: {n_out} features -> {out_path} ({time.time() - t0:.0f}s)")
    return meta


def _write(fh, geom, props, mz) -> int:
    if geom is None or geom.is_empty:
        return 0
    head = '{"type":"Feature"'
    if mz:
        head += ',"tippecanoe":{"minzoom":%d}' % max(0, mz - 1)
    fh.write(head + ',"properties":' + json.dumps(props, separators=(",", ":"), ensure_ascii=False)
             + ',"geometry":' + shapely.to_geojson(geom) + "}\n")
    return 1


def source_signature(enc_root: str) -> str:
    """Fingerprint of the S-57 files (names, sizes, times) so a changed
    exchange set triggers a new composite."""
    import hashlib
    import re
    h = hashlib.sha1()
    pat = re.compile(r"^[A-Za-z0-9_]{8}\.\d{3}$")
    for dirpath, _d, files in sorted(os.walk(enc_root)):
        for fn in sorted(files):
            if pat.match(fn):
                st = os.stat(os.path.join(dirpath, fn))
                h.update(f"{os.path.relpath(os.path.join(dirpath, fn), enc_root)}|{st.st_size}|{int(st.st_mtime)}\n".encode())
    return h.hexdigest()


def load_meta(out_dir: str) -> dict:
    with open(os.path.join(out_dir, "enc_meta.json"), encoding="utf-8") as fh:
        return json.load(fh)
