import json
import urllib.request

from s57totpk.server import RenderServer


class _Tiles:
    maxzoom = 5

    def get(self, z, x, y):
        return b"tile%d%d%d" % (z, x, y) if z < 3 else None


def test_routes_and_ranges():
    with RenderServer(tiles=_Tiles(), config={"a": 1}) as s:
        assert json.load(urllib.request.urlopen(s.url + "/config.json")) == {"a": 1}
        assert urllib.request.urlopen(s.url + "/tiles/1/0/1.pbf").read() == b"tile101"
        assert urllib.request.urlopen(s.url + "/tiles/4/0/1.pbf").status == 204
        full = urllib.request.urlopen(s.url + "/style.js").read()
        req = urllib.request.Request(s.url + "/style.js", headers={"Range": "bytes=10-19"})
        r = urllib.request.urlopen(req)
        assert r.status == 206 and r.read() == full[10:20]
        assert r.headers["Content-Range"] == f"bytes 10-19/{len(full)}"
        g = urllib.request.urlopen(s.url + "/glyphs/Regular/0-255.pbf").read()
        assert len(g) > 1000
