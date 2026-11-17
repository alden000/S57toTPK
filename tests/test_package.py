import io
import json
import sqlite3
import struct
import zipfile

import pytest

from s57totpk.mbtiles import StagingMBTiles
from s57totpk.package import PackageOptions, bundle_v1, bundle_v2, lods, write_tpk, write_tpkx


def _png(color=(10, 20, 30, 255), size=256):
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGBA", (size, size), color).save(buf, "PNG")
    return buf.getvalue()


def test_bundle_v2_layout():
    tiles = {(0, 0): b"AAAA", (1, 2): b"BBBBBB", (127, 127): b"C"}
    b = bundle_v2(tiles)
    hdr = struct.unpack("<4I3Q6I", b[:64])
    assert hdr[:4] == (3, 16384, 6, 5)
    assert hdr[5] == len(b) and hdr[6] == 40 and hdr[7] == 20 + 131072
    assert hdr[8:] == (3, 16, 16384, 5, 131072)
    for (r, c), data in tiles.items():
        idx = struct.unpack_from("<Q", b, 64 + 8 * (128 * r + c))[0]
        off, size = idx % (1 << 40), idx >> 40
        assert b[off:off + size] == data
        assert struct.unpack_from("<I", b, off - 4)[0] == size
    assert struct.unpack_from("<Q", b, 64 + 8 * 5)[0] >> 40 == 0


def test_bundle_v1_layout():
    tiles = {(0, 0): b"AAAA", (3, 1): b"BB"}
    b, bx = bundle_v1(tiles, 256, 128)
    assert len(bx) == 81952 and len(b) == struct.unpack_from("<Q", b, 24)[0]
    for (r, c), data in tiles.items():
        o = int.from_bytes(bx[16 + 5 * (c * 128 + r):][:5], "little")
        size = struct.unpack_from("<I", b, o)[0]
        assert b[o + 4:o + 4 + size] == data
    o = int.from_bytes(bx[16 + 5 * 7:][:5], "little")
    assert struct.unpack_from("<I", b, o)[0] == 0          # empty tile
    assert struct.unpack_from("<5I", b, 40) == (16, 256, 383, 128, 255)


def test_lods():
    l256, l512 = lods(256), lods(512)
    assert l256[0][1] == pytest.approx(156543.03392804097)
    assert l512[3][1] == pytest.approx(l256[3][1] / 2)
    assert l256[5][2] == l512[5][2]


@pytest.fixture
def staged(tmp_path):
    path = str(tmp_path / "tiles-day.mbtiles")
    st = StagingMBTiles(path, {"t": 1}, log=lambda *_: None)
    st.set_metadata({"format": "png", "tile_size": 256, "bounds": "-71.5,41.3,-71.2,41.6"})
    st.write_block(10, 0, 0, [(309, 381, _png()), (310, 381, _png((0, 0, 0, 0)))])
    st.write_block(11, 0, 0, [(618, 763, _png())])
    st.finish()
    return path


def test_staging_resume(tmp_path):
    path = str(tmp_path / "x.mbtiles")
    st = StagingMBTiles(path, {"a": 1}, log=lambda *_: None)
    st.write_block(5, 1, 2, [(4, 8, b"x")])
    st.close()
    st = StagingMBTiles(path, {"a": 1}, log=lambda *_: None)
    assert st.done_blocks() == {(5, 1, 2)}
    st.close()
    st = StagingMBTiles(path, {"a": 2}, log=lambda *_: None)   # settings changed: start over
    assert st.done_blocks() == set()
    st.close()


def test_tpkx(staged, tmp_path):
    out = str(tmp_path / "x.tpkx")
    write_tpkx(staged, out, PackageOptions(name="T"), log=lambda *_: None)
    with zipfile.ZipFile(out) as zf:
        assert all(i.compress_type == zipfile.ZIP_STORED for i in zf.infolist())
        names = zf.namelist()
        assert {"root.json", "iteminfo.json", "thumbnail.png"} <= set(names)
        assert "tile/L10/R0100C0100.bundle" in names and "tile/L11/R0280C0200.bundle" in names
        root = json.loads(zf.read("root.json"))
        assert root["minLOD"] == 10 and root["maxLOD"] == 11
        assert root["storageInfo"]["storageFormat"] == "esriMapCacheStorageModeCompactV2"
        assert root["tileInfo"]["origin"] == {"x": -20037508.342787, "y": 20037508.342787}
        item = json.loads(zf.read("iteminfo.json"))
        assert item["type"] == "Compact Tile Package" and "tpkx" in item["typeKeywords"]
    rasterio = pytest.importorskip("rasterio")
    with rasterio.open(out) as ds:
        assert ds.driver == "ESRIC" and ds.count == 4


@pytest.mark.parametrize("storage", ["v1", "v2"])
def test_tpk(staged, tmp_path, storage):
    out = str(tmp_path / "x.tpk")
    write_tpk(staged, out, PackageOptions(name="T", tpk_storage=storage), log=lambda *_: None)
    with zipfile.ZipFile(out) as zf:
        names = set(zf.namelist())
        assert {"v101/Layers/conf.xml", "v101/Layers/conf.cdi", "esriinfo/iteminfo.xml",
                "servicedescriptions/mapserver/mapserver.json"} <= names
        assert ("v101/Layers/_alllayers/L10/R0100C0100.bundlx" in names) == (storage == "v1")
        conf = zf.read("v101/Layers/conf.xml").decode()
        assert ("CompactV2" in conf) == (storage == "v2")
        assert conf.count("<LODInfo ") == 12


def test_mixed_format(staged, tmp_path):
    out = str(tmp_path / "m.tpkx")
    write_tpkx(staged, out, PackageOptions(fmt="mixed"), log=lambda *_: None)
    with zipfile.ZipFile(out) as zf:
        b = zf.read("tile/L10/R0100C0100.bundle")
    assert b"\xff\xd8\xff" in b       # opaque tile -> JPEG
    assert b"\x89PNG" in b            # transparent tile stays PNG
