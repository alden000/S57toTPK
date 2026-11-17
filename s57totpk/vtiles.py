"""Vector tiles for the renderer.

Two sources, same interface (``get(z, x, y) -> bytes | None``, uncompressed
MVT, single layer ``enc``):

* ``VectorTiler`` - built in, no external tools. Cuts tiles on demand from the
  composite GeoJSONSeq (shapely clip + simplify, own MVT encoder) and keeps
  every tile it made in an MBTiles cache, so a second colour scheme or a
  resumed render does not cut them again. Skin-of-earth polygons are
  simplified as a coverage so neighbouring depth areas keep shared borders.
* ``MBTilesSource`` - pre-made tiles, e.g. from tippecanoe (see tippecanoe.py).
"""
from __future__ import annotations

import gzip
import json
import math
import os
import sqlite3
import threading
import time

import numpy as np
import shapely

from . import pbf
from .s52 import SKIN_OF_EARTH

R = 6378137.0
WORLD = 2 * math.pi * R          # 40075016.686 m
ORIGIN = WORLD / 2
MAX_LAT = 85.0511287798066
EXTENT = 4096
LAYER = "enc"


def lonlat_to_merc(xy: np.ndarray) -> np.ndarray:
    lon = xy[:, 0]
    lat = np.clip(xy[:, 1], -MAX_LAT, MAX_LAT)
    x = np.radians(lon) * R
    y = np.log(np.tan(np.pi / 4 + np.radians(lat) / 2)) * R
    return np.column_stack([x, y])


def tile_bounds(z: int, x: int, y: int):
    size = WORLD / (1 << z)
    minx = -ORIGIN + x * size
    maxy = ORIGIN - y * size
    return minx, maxy - size, minx + size, maxy


# --------------------------------------------------------------- encoding --
def _cmd(cid: int, count: int) -> int:
    return (cid & 7) | (count << 3)


def _ring_area(pts) -> float:
    a = 0
    n = len(pts)
    for i in range(n):
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % n]
        a += x1 * y2 - x2 * y1
    return a


def _dedupe(pts):
    out = [pts[0]]
    for p in pts[1:]:
        if p != out[-1]:
            out.append(p)
    return out


class _Enc:
    """Builds one MVT layer."""

    def __init__(self):
        self.keys: dict[str, int] = {}
        self.values: dict[tuple, int] = {}
        self.features: list[bytes] = []

    def _tags(self, props: dict) -> list[int]:
        tags = []
        for k, v in props.items():
            if v is None:
                continue
            ki = self.keys.setdefault(k, len(self.keys))
            if isinstance(v, bool):
                vk = ("b", v)
            elif isinstance(v, int):
                vk = ("i", v)
            elif isinstance(v, float):
                vk = ("i", int(v)) if v.is_integer() and abs(v) < 2**53 else ("d", v)
            else:
                vk = ("s", str(v))
            vi = self.values.setdefault(vk, len(self.values))
            tags += (ki, vi)
        return tags

    def add(self, gtype: int, geom: list[int], props: dict):
        if not geom:
            return
        body = pbf.f_packed(2, self._tags(props)) + pbf.f_varint(3, gtype) + pbf.f_packed(4, geom)
        self.features.append(pbf.f_bytes(2, body))

    def tile(self) -> bytes:
        if not self.features:
            return b""
        out = [pbf.f_varint(15, 2), pbf.f_str(1, LAYER)]
        out += self.features
        for k in self.keys:
            out.append(pbf.f_str(3, k))
        for (t, v) in self.values:
            if t == "s":
                val = pbf.f_str(1, v)
            elif t == "d":
                val = pbf.f_double(3, v)
            elif t == "b":
                val = pbf.f_varint(7, 1 if v else 0)
            elif v >= 0:
                val = pbf.f_varint(5, v)
            else:
                val = pbf.f_sint(6, v)
            out.append(pbf.f_bytes(4, val))
        out.append(pbf.f_varint(5, EXTENT))
        return pbf.f_bytes(3, b"".join(out))


def _geom_point(pts) -> list[int]:
    out = [_cmd(1, len(pts))]
    cx = cy = 0
    for x, y in pts:
        out += (pbf.zigzag(x - cx), pbf.zigzag(y - cy))
        cx, cy = x, y
    return out


def _geom_lines(lines) -> list[int]:
    out = []
    cx = cy = 0
    for pts in lines:
        pts = _dedupe(pts)
        if len(pts) < 2:
            continue
        x, y = pts[0]
        out += (_cmd(1, 1), pbf.zigzag(x - cx), pbf.zigzag(y - cy))
        cx, cy = x, y
        out.append(_cmd(2, len(pts) - 1))
        for x, y in pts[1:]:
            out += (pbf.zigzag(x - cx), pbf.zigzag(y - cy))
            cx, cy = x, y
    return out


def _geom_polys(polys) -> list[int]:
    """polys: list of polygons, each a list of rings (closed point lists)."""
    out = []
    cx = cy = 0
    for rings in polys:
        for ri, pts in enumerate(rings):
            pts = _dedupe(pts)
            if len(pts) > 1 and pts[0] == pts[-1]:
                pts = pts[:-1]
            if len(pts) < 3:
                if ri == 0:
                    break  # degenerate exterior: drop the whole polygon
                continue
            a = _ring_area(pts)
            if a == 0:
                if ri == 0:
                    break
                continue
            if (ri == 0 and a < 0) or (ri > 0 and a > 0):
                pts = pts[::-1]
            x, y = pts[0]
            out += (_cmd(1, 1), pbf.zigzag(x - cx), pbf.zigzag(y - cy))
            cx, cy = x, y
            out.append(_cmd(2, len(pts) - 1))
            for x, y in pts[1:]:
                out += (pbf.zigzag(x - cx), pbf.zigzag(y - cy))
                cx, cy = x, y
            out.append(_cmd(7, 1))
    return out


# ------------------------------------------------------------------ tiler --
def load_geojsons(path: str, log=print):
    props, gstrs = [], []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip().lstrip("\x1e")
            if not line:
                continue
            gi = line.rfind(',"geometry":')
            pi = line.find('"properties":')
            if gi > 0 and pi > 0 and line.endswith("}"):
                props.append(json.loads(line[pi + 13:gi]))
                gstrs.append(line[gi + 12:-1])
            else:
                f = json.loads(line)
                props.append(f.get("properties") or {})
                gstrs.append(json.dumps(f["geometry"]))
    geoms = shapely.from_geojson(np.array(gstrs, dtype=object))
    return props, geoms


class VectorTiler:
    def __init__(self, geojsons: str, maxzoom: int = 16, cache_path: str | None = None,
                 buffer: int = 80, simplification: float = 2.0, log=print):
        t0 = time.time()
        self.maxzoom = maxzoom
        self.buffer = buffer
        self.simplification = simplification
        self.log = log
        self.props, geoms = load_geojsons(geojsons, log)
        geoms = shapely.transform(geoms, lonlat_to_merc)
        self.geoms = geoms
        tid = shapely.get_type_id(geoms)
        self.kind = np.where(np.isin(tid, (0, 4)), 1, np.where(np.isin(tid, (1, 5)), 2, 3))
        self.minz = np.array([max(0, int(p.get("_mz", 0)) - 1) for p in self.props], dtype=np.int16)
        self.skin = np.array([p.get("OBJL") in SKIN_OF_EARTH and k == 3
                              for p, k in zip(self.props, self.kind)], dtype=bool)
        # drop bookkeeping keys the style does not need
        for p in self.props:
            p.pop("_cs", None)
            p.pop("SCAMIN", None)
        self.tree = shapely.STRtree(geoms)
        self._simp: dict[int, np.ndarray] = {}
        self._lock = threading.Lock()
        self._db = None
        self._db_lock = threading.Lock()
        if cache_path:
            self._open_cache(cache_path, geojsons)
        log(f"Vector tiler: {len(geoms)} features loaded ({time.time() - t0:.1f}s)")

    # -- cache ---------------------------------------------------------
    def _open_cache(self, path: str, src: str):
        st = os.stat(src)
        fp = f"{os.path.abspath(src)}|{st.st_size}|{int(st.st_mtime)}|{self.maxzoom}|{self.simplification}|v1"
        db = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("CREATE TABLE IF NOT EXISTS metadata (name TEXT PRIMARY KEY, value TEXT)")
        db.execute("CREATE TABLE IF NOT EXISTS tiles (zoom_level INTEGER, tile_column INTEGER, "
                   "tile_row INTEGER, tile_data BLOB, PRIMARY KEY (zoom_level, tile_column, tile_row))")
        row = db.execute("SELECT value FROM metadata WHERE name='s57totpk_source'").fetchone()
        if not row or row[0] != fp:
            db.execute("DELETE FROM tiles")
            db.execute("INSERT OR REPLACE INTO metadata VALUES ('s57totpk_source', ?)", (fp,))
            for k, v in (("name", "enc"), ("format", "pbf"), ("minzoom", "0"),
                         ("maxzoom", str(self.maxzoom))):
                db.execute("INSERT OR REPLACE INTO metadata VALUES (?, ?)", (k, v))
        self._db = db

    def close(self):
        if self._db is not None:
            self._db.close()
            self._db = None

    # -- simplification --------------------------------------------------
    def _simplified(self, z: int) -> np.ndarray:
        if z >= self.maxzoom:
            return self.geoms
        with self._lock:
            if z in self._simp:
                return self._simp[z]
            tol = self.simplification * WORLD / (1 << z) / EXTENT
            g = self.geoms.copy()
            use = self.minz <= z
            lines = use & (self.kind == 2)
            areas = use & (self.kind == 3) & ~self.skin
            skin = use & self.skin
            if lines.any():
                g[lines] = shapely.simplify(g[lines], tol, preserve_topology=False)
            if areas.any():
                g[areas] = shapely.simplify(g[areas], tol, preserve_topology=True)
            if skin.any():
                try:
                    g[skin] = shapely.coverage_simplify(g[skin], tol, simplify_boundary=True)
                except Exception:  # noqa: BLE001 - not a clean coverage
                    g[skin] = shapely.simplify(g[skin], tol, preserve_topology=True)
            self._simp[z] = g
            return g

    # -- tiles -----------------------------------------------------------
    def get(self, z: int, x: int, y: int) -> bytes | None:
        if self._db is not None:
            with self._db_lock:
                row = self._db.execute(
                    "SELECT tile_data FROM tiles WHERE zoom_level=? AND tile_column=? AND tile_row=?",
                    (z, x, (1 << z) - 1 - y)).fetchone()
            if row is not None:
                return row[0] or None
        data = self.make(z, x, y)
        if self._db is not None:
            with self._db_lock:
                self._db.execute("INSERT OR REPLACE INTO tiles VALUES (?, ?, ?, ?)",
                                 (z, x, (1 << z) - 1 - y, data))
        return data or None

    def make(self, z: int, x: int, y: int) -> bytes:
        if z > self.maxzoom:
            return b""
        minx, miny, maxx, maxy = tile_bounds(z, x, y)
        size = maxx - minx
        b = size * self.buffer / EXTENT
        idx = self.tree.query(shapely.box(minx - b, miny - b, maxx + b, maxy + b))
        if len(idx) == 0:
            return b""
        idx = np.sort(idx[self.minz[idx] <= z])
        if len(idx) == 0:
            return b""
        g = self._simplified(z)[idx]
        kinds = self.kind[idx]
        scale = EXTENT / size
        enc = _Enc()

        def q(coords):
            ix = np.rint((coords[:, 0] - minx) * scale).astype(np.int64)
            iy = np.rint((maxy - coords[:, 1]) * scale).astype(np.int64)
            return list(zip(ix.tolist(), iy.tolist()))

        clip = np.empty(len(idx), dtype=object)
        nonpt = kinds != 1
        if nonpt.any():
            clip[nonpt] = shapely.clip_by_rect(g[nonpt], minx - b, miny - b, maxx + b, maxy + b)
        clip[~nonpt] = g[~nonpt]
        for j, i in enumerate(idx):
            geom = clip[j]
            if geom is None or geom.is_empty:
                continue
            k = kinds[j]
            props = self.props[i]
            if k == 1:
                pts = [p for p in q(shapely.get_coordinates(geom)) if 0 <= p[0] < EXTENT and 0 <= p[1] < EXTENT]
                if pts:
                    enc.add(1, _geom_point(pts), props)
            elif k == 2:
                lines = [q(shapely.get_coordinates(p)) for p in shapely.get_parts(geom)
                         if shapely.get_type_id(p) in (1, 2)]
                enc.add(2, _geom_lines(lines), props)
            else:
                polys = []
                for p in shapely.get_parts(geom):
                    if shapely.get_type_id(p) != 3:
                        continue
                    rings = [q(shapely.get_coordinates(p.exterior))]
                    rings += [q(shapely.get_coordinates(r)) for r in p.interiors]
                    polys.append(rings)
                enc.add(3, _geom_polys(polys), props)
        return enc.tile()


class MBTilesSource:
    """Pre-made vector tiles (e.g. tippecanoe output); gzip is undone."""

    def __init__(self, path: str):
        self.path = path
        self._db = sqlite3.connect(f"file:{path}?mode=ro", uri=True, check_same_thread=False)
        self._lock = threading.Lock()
        md = dict(self._db.execute("SELECT name, value FROM metadata").fetchall())
        self.maxzoom = int(md.get("maxzoom", 14))
        self.minzoom = int(md.get("minzoom", 0))

    def get(self, z, x, y):
        with self._lock:
            row = self._db.execute(
                "SELECT tile_data FROM tiles WHERE zoom_level=? AND tile_column=? AND tile_row=?",
                (z, x, (1 << z) - 1 - y)).fetchone()
        if not row or not row[0]:
            return None
        data = row[0]
        if data[:2] == b"\x1f\x8b":
            data = gzip.decompress(data)
        return data

    def close(self):
        self._db.close()
