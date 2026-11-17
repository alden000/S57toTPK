import json

from s57totpk import pbf
from s57totpk.vtiles import EXTENT, VectorTiler, tile_bounds


def _decode(tile):
    layers = [v for f, w, v in pbf.iter_fields(tile) if f == 3]
    assert len(layers) == 1
    keys, values, feats, name, ext = [], [], [], None, None
    for f, w, v in pbf.iter_fields(layers[0]):
        if f == 1:
            name = v.decode()
        elif f == 3:
            keys.append(v.decode())
        elif f == 4:
            vf, _vw, vv = next(iter(pbf.iter_fields(v)))
            values.append(vv.decode() if vf == 1 else vv)
        elif f == 5:
            ext = v
        elif f == 2:
            ft = {}
            for ff, _w, vv in pbf.iter_fields(v):
                if ff in (2, 4):
                    arr, i = [], 0
                    while i < len(vv):
                        n, i = pbf.read_varint(vv, i)
                        arr.append(n)
                    ft[ff] = arr
                else:
                    ft[ff] = vv
            feats.append(ft)
    return name, ext, keys, values, feats


def _geom(cmds):
    """Decode MVT commands into rings/lines of absolute coords."""
    out, cur, x, y, i = [], None, 0, 0, 0
    zz = lambda n: (n >> 1) ^ -(n & 1)  # noqa: E731
    while i < len(cmds):
        cid, cnt = cmds[i] & 7, cmds[i] >> 3
        i += 1
        if cid == 7:
            continue
        for _ in range(cnt):
            x += zz(cmds[i]); y += zz(cmds[i + 1]); i += 2
            if cid == 1:
                cur = [(x, y)]
                out.append(cur)
            else:
                cur.append((x, y))
    return out


def _area(r):
    return sum(r[i][0] * r[(i + 1) % len(r)][1] - r[(i + 1) % len(r)][0] * r[i][1] for i in range(len(r)))


def test_tile_roundtrip(tmp_path):
    p = tmp_path / "enc.geojsons"
    feats = [
        {"type": "Feature", "properties": {"OBJL": "DEPARE", "_fill": "DEPVS", "_p": 1},
         "geometry": {"type": "Polygon", "coordinates": [[[10, 10], [20, 10], [20, 20], [10, 20], [10, 10]],
                                                          [[14, 14], [14, 16], [16, 16], [16, 14], [14, 14]]]}},
        {"type": "Feature", "properties": {"OBJL": "COALNE", "_lc": "CSTLN", "_lw": 1.6},
         "geometry": {"type": "LineString", "coordinates": [[5, 5], [30, 6]]}},
        {"type": "Feature", "properties": {"OBJL": "SOUNDG", "_snd": "12", "_mz": 12},
         "geometry": {"type": "Point", "coordinates": [15, 15]}},
    ]
    p.write_text("\n".join(json.dumps(f) for f in feats) + "\n")
    t = VectorTiler(str(p), maxzoom=10, log=lambda *_: None)
    name, ext, keys, values, fs = _decode(t.make(3, 4, 3))  # lon 0..45, lat 0..41
    assert name == "enc" and ext == EXTENT
    types = sorted(f[3] for f in fs)
    assert types == [2, 3]  # sounding has _mz 12 -> not in a z3 tile
    poly = next(f for f in fs if f[3] == 3)
    rings = _geom(poly[4])
    assert _area(rings[0]) > 0 and _area(rings[1]) < 0   # exterior positive, hole negative (y down)
    props = dict(zip([keys[i] for i in poly[2][::2]], [values[i] for i in poly[2][1::2]]))
    assert props["OBJL"] == "DEPARE" and props["_fill"] == "DEPVS"
    _, _, _, _, fs10 = _decode(t.make(10, 554, 468))   # maxzoom tile carries the z12 sounding
    assert 1 in [f[3] for f in fs10]
    assert t.make(11, 1109, 937) == b""                 # beyond maxzoom: overzoomed by the client
    assert t.make(3, 0, 0) == b""


def test_tile_bounds():
    minx, miny, maxx, maxy = tile_bounds(0, 0, 0)
    assert round(maxx) == 20037508 and round(miny) == -20037508
