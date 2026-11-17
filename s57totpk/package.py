"""Write ArcGIS tile packages from the staged MBTiles.

.tpkx  Esri "tile-package-spec" 1.0: uncompressed zip with root.json,
       iteminfo.json, thumbnail.png and tile/Lnn/RrrrrCcccc.bundle
       (Compact Cache V2, Esri "raster-tiles-compactcache").
.tpk   Classic tile package: esriinfo/iteminfo.xml, item.pkinfo,
       servicedescriptions/mapserver/mapserver.json and
       v101/Layers/{conf.xml, conf.cdi, _alllayers/Lnn/...}. Bundles are
       Compact Cache V1 (.bundle + .bundlx) by default, as Esri documents for
       .tpk; Compact V2 can be chosen instead.

Tiling scheme: Web Mercator (WKID 102100 / 3857), origin
(-20037508.342787, 20037508.342787), the standard 24-level ArcGIS Online
LOD list. For 256 px tiles resolution(z) = 156543.03392804097 / 2^z at
96 dpi; 512 px tiles cover the same ground per tile (half the resolution
value) at 192 dpi, so LOD scales are identical.
"""
from __future__ import annotations

import io
import json
import math
import os
import struct
import tempfile
import time
import uuid
import zipfile
from dataclasses import dataclass

from .mbtiles import MBTilesReader

ORIGIN_X = -20037508.342787
ORIGIN_Y = 20037508.342787
RES0_256 = 156543.03392804097
SCALE0 = 591657527.591555
NLODS = 24
PACKET = 128

WKT_3857 = ('PROJCS["WGS_1984_Web_Mercator_Auxiliary_Sphere",GEOGCS["GCS_WGS_1984",DATUM["D_WGS_1984",'
            'SPHEROID["WGS_1984",6378137.0,298.257223563]],PRIMEM["Greenwich",0.0],UNIT["Degree",0.0174532925199433]],'
            'PROJECTION["Mercator_Auxiliary_Sphere"],PARAMETER["False_Easting",0.0],PARAMETER["False_Northing",0.0],'
            'PARAMETER["Central_Meridian",0.0],PARAMETER["Standard_Parallel_1",0.0],PARAMETER["Auxiliary_Sphere_Type",0.0],'
            'UNIT["Meter",1.0],AUTHORITY["EPSG",3857]]')


@dataclass
class PackageOptions:
    name: str = "ENC"
    fmt: str = "png"            # png | jpeg | mixed
    jpeg_quality: int = 90
    jpeg_background: tuple = (255, 255, 255)
    png_colors: int = 0         # 0 = full colour; 2..256 = palette PNG (smaller)
    tpk_storage: str = "v1"     # v1 | v2 (bundles inside .tpk)
    description: str = ""
    tags: str = "ENC, S-57, nautical chart"
    credits: str = ""


def lods(tile_size: int):
    f = 256 / tile_size
    return [(z, RES0_256 / (1 << z) * f, SCALE0 / (1 << z)) for z in range(NLODS)]


def dpi_for(tile_size: int) -> int:
    return 96 * tile_size // 256


# --------------------------------------------------------------- bundles --
def bundle_v2(tiles: dict[tuple[int, int], bytes]) -> bytes:
    """tiles: {(row_in_bundle, col_in_bundle): data}"""
    index = [0] * (PACKET * PACKET)
    body = io.BytesIO()
    off = 64 + PACKET * PACKET * 8
    maxsize = 0
    for (r, c), data in sorted(tiles.items()):
        body.write(struct.pack("<I", len(data)))
        off += 4
        index[r * PACKET + c] = off | (len(data) << 40)
        body.write(data)
        off += len(data)
        maxsize = max(maxsize, len(data))
    idx_size = PACKET * PACKET * 8
    header = struct.pack("<4I3Q6I", 3, PACKET * PACKET, maxsize, 5, 0, off, 40,
                         20 + idx_size, 3, 16, PACKET * PACKET, 5, idx_size)
    return header + struct.pack(f"<{PACKET * PACKET}Q", *index) + body.getvalue()


def bundle_v1(tiles: dict[tuple[int, int], bytes], row0: int, col0: int) -> tuple[bytes, bytes]:
    """Compact Cache V1: returns (bundle, bundlx). Layout as MapProxy's
    long-standing implementation: 60-byte header, 16384 empty 4-byte size
    slots, then size-prefixed tiles; the .bundlx index is column-major with
    5-byte offsets pointing at a tile's size prefix."""
    hdr_size = 60
    slots = PACKET * PACKET * 4
    offsets = [hdr_size + 4 * i for i in range(PACKET * PACKET)]  # empty slots
    body = io.BytesIO()
    off = hdr_size + slots
    maxsize = 0
    for (r, c), data in sorted(tiles.items(), key=lambda t: (t[0][1], t[0][0])):
        offsets[c * PACKET + r] = off
        body.write(struct.pack("<I", len(data)))
        body.write(data)
        off += 4 + len(data)
        maxsize = max(maxsize, len(data))
    header = struct.pack("<4I3Q5I", 3, PACKET * PACKET, maxsize, 5, 4 * len(tiles), off, 40, 16,
                         row0, row0 + PACKET - 1, col0, col0 + PACKET - 1)
    bundle = header + b"\x00" * slots + body.getvalue()
    bundlx = (b"\x03\x00\x00\x00\x10\x00\x00\x00\x00\x40\x00\x00\x05\x00\x00\x00"
              + b"".join(struct.pack("<Q", o)[:5] for o in offsets)
              + b"\x00\x00\x00\x00\x10\x00\x00\x00\x10\x00\x00\x00\x00\x00\x00\x00")
    return bundle, bundlx


# --------------------------------------------------------- tile encoding --
class TileEncoder:
    def __init__(self, src_format: str, opts: PackageOptions):
        self.src = src_format
        self.o = opts
        self.used_png = self.used_jpeg = False

    def __call__(self, data: bytes) -> bytes:
        from PIL import Image
        fmt = self.o.fmt
        if fmt == "png" and self.src == "png" and not self.o.png_colors:
            self.used_png = True
            return data
        im = Image.open(io.BytesIO(data))
        im.load()
        if im.mode != "RGBA":
            im = im.convert("RGBA")
        opaque = im.getchannel("A").getextrema()[0] == 255
        if fmt == "jpeg" or (fmt == "mixed" and opaque):
            bg = Image.new("RGB", im.size, self.o.jpeg_background)
            bg.paste(im, mask=im.getchannel("A"))
            buf = io.BytesIO()
            bg.save(buf, "JPEG", quality=self.o.jpeg_quality, optimize=True)
            self.used_jpeg = True
            return buf.getvalue()
        buf = io.BytesIO()
        if self.o.png_colors:
            q = im.quantize(colors=self.o.png_colors, method=Image.Quantize.FASTOCTREE)
            q.save(buf, "PNG", optimize=True)
        else:
            im.save(buf, "PNG", optimize=False, compress_level=6)
        self.used_png = True
        return buf.getvalue()

    @property
    def cache_format(self) -> str:
        return {"png": "PNG", "jpeg": "JPEG", "mixed": "MIXED"}[self.o.fmt]


def iter_bundles(src: MBTilesReader, enc: TileEncoder):
    """Yield (z, row0, col0, {(r, c): data}) for every non-empty bundle."""
    for z in src.zooms():
        keys = sorted({(y // PACKET, x // PACKET) for x, y in src.tiles_xyz(z)})
        for br, bc in keys:
            row0, col0 = br * PACKET, bc * PACKET
            tiles = {}
            for x, y, data in src.region(z, col0, col0 + PACKET - 1, row0, row0 + PACKET - 1):
                tiles[(y - row0, x - col0)] = enc(data)
            if tiles:
                yield z, row0, col0, tiles


# --------------------------------------------------------------- extents --
def merc_from_lonlat(lon, lat):
    lat = max(min(lat, 85.0511287798), -85.0511287798)
    x = math.radians(lon) * 6378137.0
    y = math.log(math.tan(math.pi / 4 + math.radians(lat) / 2)) * 6378137.0
    return x, y


def extent_from_bounds(b):
    x0, y0 = merc_from_lonlat(b[0], b[1])
    x1, y1 = merc_from_lonlat(b[2], b[3])
    return {"xmin": x0, "ymin": y0, "xmax": x1, "ymax": y1}


def _sr():
    return {"wkid": 102100, "latestWkid": 3857}


def thumbnail(src: MBTilesReader, size=(200, 133)) -> bytes:
    from PIL import Image
    zs = src.zooms()
    img = Image.new("RGB", size, (220, 230, 235))
    if zs:
        z = zs[0]
        coords = list(src.tiles_xyz(z))
        if coords:
            xs = [c[0] for c in coords]
            ys = [c[1] for c in coords]
            x0, y0 = min(xs), min(ys)
            w, h = max(xs) - x0 + 1, max(ys) - y0 + 1
            if w * h <= 64:
                first = Image.open(io.BytesIO(src.get(z, coords[0][0], coords[0][1])))
                ts = first.size[0]
                mosaic = Image.new("RGBA", (w * ts, h * ts), (220, 230, 235, 255))
                for x, y in coords:
                    t = Image.open(io.BytesIO(src.get(z, x, y))).convert("RGBA")
                    mosaic.alpha_composite(t, ((x - x0) * ts, (y - y0) * ts))
                mosaic.thumbnail(size)
                img.paste(mosaic.convert("RGB"), ((size[0] - mosaic.size[0]) // 2, (size[1] - mosaic.size[1]) // 2))
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


# ------------------------------------------------------------------ tpkx --
def write_tpkx(mbtiles: str, out_path: str, opts: PackageOptions, log=print) -> str:
    src = MBTilesReader(mbtiles)
    md = src.meta
    tile_size = int(md.get("tile_size", 256))
    bounds = [float(v) for v in md["bounds"].split(",")]
    zs = src.zooms()
    if not zs:
        raise RuntimeError(f"{mbtiles} has no tiles")
    enc = TileEncoder(md.get("format", "png"), opts)
    tmp = out_path + ".partial"
    ext = extent_from_bounds(bounds)
    n_tiles = 0
    with zipfile.ZipFile(tmp, "w", compression=zipfile.ZIP_STORED, allowZip64=True) as zf:
        zf.writestr("tile/", b"")
        last_z = None
        for z, row0, col0, tiles in iter_bundles(src, enc):
            if z != last_z:
                zf.writestr(f"tile/L{z:02d}/", b"")
                last_z = z
            name = f"tile/L{z:02d}/R{row0:04x}C{col0:04x}.bundle"
            _write_member(zf, name, bundle_v2(tiles))
            n_tiles += len(tiles)
        root = {
            "version": 1.0,
            "name": opts.name,
            "serviceDescription": opts.description,
            "tileBundlesPath": "./tile",
            "tileImageInfo": {"format": enc.cache_format,
                              "compressionQuality": opts.jpeg_quality if opts.fmt != "png" else 0},
            "storageInfo": {"storageFormat": "esriMapCacheStorageModeCompactV2", "packetSize": PACKET},
            "tileInfo": {
                "rows": tile_size, "cols": tile_size, "dpi": dpi_for(tile_size),
                "origin": {"x": ORIGIN_X, "y": ORIGIN_Y},
                "spatialReference": _sr(),
                "lods": [{"level": z, "resolution": r, "scale": s} for z, r, s in lods(tile_size)],
            },
            "minLOD": zs[0], "maxLOD": zs[-1],
            "minScale": SCALE0 / (1 << zs[0]), "maxScale": SCALE0 / (1 << zs[-1]),
            "resampling": True,
            "spatialReference": _sr(),
            "units": "esriMeters",
            "initialExtent": {**ext, "spatialReference": _sr()},
            "fullExtent": {**ext, "spatialReference": _sr()},
            "exportTilesAllowed": False,
        }
        item = {
            "creator": "s57totpk",
            "name": opts.name,
            "guid": str(uuid.uuid4()).upper(),
            "version": 1.0,
            "created": int(time.time() * 1000),
            "snippet": opts.description or opts.name,
            "description": opts.description,
            "summary": opts.description or opts.name,
            "title": opts.name,
            "tags": opts.tags,
            "type": "Compact Tile Package",
            "typeKeywords": ["Compact Tile Package", "Tile Package", "tpkx"],
            "thumbnail": "./thumbnail.png",
            "extent": {"xmin": bounds[0], "ymin": bounds[1], "xmax": bounds[2], "ymax": bounds[3],
                       "spatialReference": {"wkid": 4326, "latestWkid": 4326}},
            "spatialReference": _sr(),
            "accessInformation": opts.credits,
        }
        zf.writestr("root.json", json.dumps(root, indent=1))
        zf.writestr("iteminfo.json", json.dumps(item, indent=1))
        zf.writestr("thumbnail.png", thumbnail(src))
    os.replace(tmp, out_path)
    src.close()
    log(f"Wrote {out_path}: {n_tiles} tiles, zoom {zs[0]}-{zs[-1]}, {os.path.getsize(out_path) / 1e6:.1f} MB")
    return out_path


def _write_member(zf: zipfile.ZipFile, name: str, data: bytes):
    zi = zipfile.ZipInfo(name, date_time=time.localtime()[:6])
    zi.compress_type = zipfile.ZIP_STORED
    with zf.open(zi, "w", force_zip64=len(data) > 0x7FFF0000) as fh:
        fh.write(data)


# ------------------------------------------------------------------- tpk --
def conf_xml(tile_size: int, fmt: str, quality: int, storage: str, max_level: int = NLODS - 1) -> str:
    lod_xml = "".join(
        f'<LODInfo xsi:type="typens:LODInfo"><LevelID>{z}</LevelID><Scale>{s!r}</Scale>'
        f"<Resolution>{r!r}</Resolution></LODInfo>" for z, r, s in lods(tile_size)[:max_level + 1])
    st = "esriMapCacheStorageModeCompactV2" if storage == "v2" else "esriMapCacheStorageModeCompact"
    return (
        '<?xml version="1.0" encoding="utf-8" ?>'
        '<CacheInfo xsi:type="typens:CacheInfo" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
        'xmlns:xs="http://www.w3.org/2001/XMLSchema" xmlns:typens="http://www.esri.com/schemas/ArcGIS/10.1">'
        '<TileCacheInfo xsi:type="typens:TileCacheInfo">'
        '<SpatialReference xsi:type="typens:ProjectedCoordinateSystem">'
        f"<WKT>{WKT_3857}</WKT>"
        "<XOrigin>-20037700</XOrigin><YOrigin>-30241100</YOrigin><XYScale>148923141.92838538</XYScale>"
        "<ZOrigin>-100000</ZOrigin><ZScale>10000</ZScale><MOrigin>-100000</MOrigin><MScale>10000</MScale>"
        "<XYTolerance>0.001</XYTolerance><ZTolerance>0.001</ZTolerance><MTolerance>0.001</MTolerance>"
        "<HighPrecision>true</HighPrecision><WKID>102100</WKID><LatestWKID>3857</LatestWKID>"
        "</SpatialReference>"
        f'<TileOrigin xsi:type="typens:PointN"><X>{ORIGIN_X}</X><Y>{ORIGIN_Y}</Y></TileOrigin>'
        f"<TileCols>{tile_size}</TileCols><TileRows>{tile_size}</TileRows><DPI>{dpi_for(tile_size)}</DPI>"
        f"<PreciseDPI>{dpi_for(tile_size)}</PreciseDPI>"
        f'<LODInfos xsi:type="typens:ArrayOfLODInfo">{lod_xml}</LODInfos>'
        "</TileCacheInfo>"
        '<TileImageInfo xsi:type="typens:TileImageInfo">'
        f"<CacheTileFormat>{fmt}</CacheTileFormat><CompressionQuality>{quality}</CompressionQuality>"
        "<Antialiasing>true</Antialiasing></TileImageInfo>"
        '<CacheStorageInfo xsi:type="typens:CacheStorageInfo">'
        f"<StorageFormat>{st}</StorageFormat><PacketSize>{PACKET}</PacketSize></CacheStorageInfo>"
        "</CacheInfo>")


def conf_cdi(ext: dict) -> str:
    return ('<?xml version="1.0" encoding="utf-8" ?>'
            '<EnvelopeN xsi:type="typens:EnvelopeN" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
            'xmlns:xs="http://www.w3.org/2001/XMLSchema" xmlns:typens="http://www.esri.com/schemas/ArcGIS/10.1">'
            f"<XMin>{ext['xmin']!r}</XMin><YMin>{ext['ymin']!r}</YMin><XMax>{ext['xmax']!r}</XMax><YMax>{ext['ymax']!r}</YMax>"
            '<SpatialReference xsi:type="typens:ProjectedCoordinateSystem">'
            f"<WKT>{WKT_3857}</WKT><WKID>102100</WKID><LatestWKID>3857</LatestWKID></SpatialReference>"
            "</EnvelopeN>")


def _esc(s: str) -> str:
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def write_tpk(mbtiles: str, out_path: str, opts: PackageOptions, log=print) -> str:
    src = MBTilesReader(mbtiles)
    md = src.meta
    tile_size = int(md.get("tile_size", 256))
    bounds = [float(v) for v in md["bounds"].split(",")]
    zs = src.zooms()
    if not zs:
        raise RuntimeError(f"{mbtiles} has no tiles")
    enc = TileEncoder(md.get("format", "png"), opts)
    ext = extent_from_bounds(bounds)
    tmp = out_path + ".partial"
    guid = "{" + str(uuid.uuid4()).upper() + "}"
    n_tiles = 0
    base = "v101/Layers"
    with zipfile.ZipFile(tmp, "w", compression=zipfile.ZIP_STORED, allowZip64=True) as zf:
        for z, row0, col0, tiles in iter_bundles(src, enc):
            stem = f"{base}/_alllayers/L{z:02d}/R{row0:04x}C{col0:04x}"
            if opts.tpk_storage == "v2":
                _write_member(zf, stem + ".bundle", bundle_v2(tiles))
            else:
                b, bx = bundle_v1(tiles, row0, col0)
                _write_member(zf, stem + ".bundle", b)
                _write_member(zf, stem + ".bundlx", bx)
            n_tiles += len(tiles)
        q = opts.jpeg_quality if opts.fmt != "png" else 0
        zf.writestr(f"{base}/conf.xml", conf_xml(tile_size, enc.cache_format, q, opts.tpk_storage, zs[-1]))
        zf.writestr(f"{base}/conf.cdi", conf_cdi(ext))
        created = time.strftime("%Y%m%d")
        zf.writestr("esriinfo/iteminfo.xml", (
            '<?xml version="1.0" encoding="utf-8"?>'
            "<ESRI_ItemInformation Culture=\"en-US\">"
            f"<guid>{guid}</guid><version>10.1</version><name>{_esc(opts.name)}</name>"
            f"<title>{_esc(opts.name)}</title><summary>{_esc(opts.description or opts.name)}</summary>"
            f"<description>{_esc(opts.description)}</description><tags>{_esc(opts.tags)}</tags>"
            f"<snippet>{_esc(opts.description or opts.name)}</snippet>"
            f"<accessinformation>{_esc(opts.credits)}</accessinformation><licenseinfo></licenseinfo>"
            "<type>Tile Package</type><typekeywords><typekeyword>Tile Package</typekeyword>"
            "<typekeyword>tpk</typekeyword></typekeywords>"
            f"<extent><xmin>{bounds[0]}</xmin><ymin>{bounds[1]}</ymin><xmax>{bounds[2]}</xmax><ymax>{bounds[3]}</ymax></extent>"
            "<spatialreference>WGS_1984_Web_Mercator_Auxiliary_Sphere</spatialreference>"
            "<thumbnail>thumbnail/thumbnail.png</thumbnail>"
            f"<minScale>{SCALE0 / (1 << zs[0])!r}</minScale><maxScale>{SCALE0 / (1 << zs[-1])!r}</maxScale>"
            f"<created>{created}</created>"
            "</ESRI_ItemInformation>"))
        zf.writestr("esriinfo/item.pkinfo", (
            '<?xml version="1.0" encoding="utf-8"?>'
            f"<pkinfo Culture='en-US'><ID>{guid}</ID><name>{_esc(opts.name)}</name><version>10.1</version>"
            "<size>-1</size><created></created><type>Tile Package</type><servable>false</servable>"
            "<packagelocation></packagelocation><pkinfolocation></pkinfolocation></pkinfo>"))
        zf.writestr("esriinfo/thumbnail/thumbnail.png", thumbnail(src))
        geo = {"xmin": bounds[0], "ymin": bounds[1], "xmax": bounds[2], "ymax": bounds[3],
               "spatialReference": {"wkid": 4326}}
        ms = {
            "contents": {
                "serviceDescription": opts.description, "mapName": "Layers", "description": opts.description,
                "copyrightText": opts.credits, "supportsDynamicLayers": False,
                "layers": [{"id": 0, "name": opts.name, "parentLayerId": -1, "defaultVisibility": True,
                            "subLayerIds": None, "minScale": 0, "maxScale": 0}],
                "spatialReference": _sr(), "singleFusedMapCache": True,
                "tileInfo": {"rows": tile_size, "cols": tile_size, "dpi": dpi_for(tile_size),
                             "format": enc.cache_format, "compressionQuality": q,
                             "origin": {"x": ORIGIN_X, "y": ORIGIN_Y}, "spatialReference": _sr(),
                             "lods": [{"level": z, "resolution": r, "scale": s}
                                      for z, r, s in lods(tile_size)[:zs[-1] + 1]]},
                "initialExtent": {**ext, "spatialReference": _sr()},
                "fullExtent": {**ext, "spatialReference": _sr()},
                "minScale": SCALE0 / (1 << zs[0]), "maxScale": SCALE0 / (1 << zs[-1]),
                "units": "esriMeters", "supportedImageFormatTypes": "PNG32,PNG24,PNG,JPG",
                "capabilities": "Map", "exportTilesAllowed": False,
            },
            "resourceInfo": {"geoFullExtent": geo, "geoInitialExtent": geo},
            "resources": [{"name": "layers", "contents": {"layers": []}},
                          {"name": "legend", "contents": {"layers": []}}],
        }
        zf.writestr("servicedescriptions/mapserver/mapserver.json", json.dumps(ms, indent=1))
    os.replace(tmp, out_path)
    src.close()
    log(f"Wrote {out_path}: {n_tiles} tiles ({opts.tpk_storage} bundles), zoom {zs[0]}-{zs[-1]}, "
        f"{os.path.getsize(out_path) / 1e6:.1f} MB")
    return out_path


def write_package(mbtiles: str, out_path: str, opts: PackageOptions, log=print) -> str:
    if out_path.lower().endswith(".tpkx"):
        return write_tpkx(mbtiles, out_path, opts, log)
    if out_path.lower().endswith(".tpk"):
        return write_tpk(mbtiles, out_path, opts, log)
    raise ValueError("output must end in .tpk or .tpkx")


def extract_cache(package: str, dest: str) -> str:
    """Unpack a .tpk/.tpkx (for inspection or GDAL checks). Returns the path
    of conf.xml (tpk) or root.json (tpkx)."""
    with zipfile.ZipFile(package) as zf:
        zf.extractall(dest)
    for cand in ("v101/Layers/conf.xml", "root.json"):
        p = os.path.join(dest, cand)
        if os.path.exists(p):
            return p
    raise RuntimeError("no conf.xml/root.json in package")


__all__ = ["PackageOptions", "write_package", "write_tpk", "write_tpkx", "bundle_v1", "bundle_v2",
           "lods", "extract_cache", "tempfile"]
