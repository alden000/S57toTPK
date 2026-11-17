"""Local HTTP server for the render page: static files (with byte ranges),
vector tiles, SDF glyphs and the page config. Binds to 127.0.0.1 only."""
from __future__ import annotations

import json
import mimetypes
import os
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote, urlparse

WEB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")
_TILE = re.compile(r"^/tiles/(\d+)/(\d+)/(\d+)\.pbf$")
_GLYPH = re.compile(r"^/glyphs/([^/]+)/(\d+)-(\d+)\.pbf$")
_RANGE = re.compile(r"bytes=(\d*)-(\d*)$")

mimetypes.add_type("application/javascript", ".js")
mimetypes.add_type("application/x-protobuf", ".pbf")


class _Handler(BaseHTTPRequestHandler):
    server_version = "s57totpk"
    protocol_version = "HTTP/1.1"

    def log_message(self, *_args):  # quiet
        pass

    def _send(self, code: int, body: bytes, ctype: str, extra: dict | None = None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        srv = self.server
        path = unquote(urlparse(self.path).path)
        try:
            m = _TILE.match(path)
            if m:
                z, x, y = map(int, m.groups())
                data = srv.tiles.get(z, x, y) if srv.tiles else None
                if not data:
                    return self._send(204, b"", "application/x-protobuf")
                return self._send(200, data, "application/x-protobuf")
            m = _GLYPH.match(path)
            if m:
                data = srv.glyphs.range_pbf(m.group(1), int(m.group(2)))
                return self._send(200, data, "application/x-protobuf")
            if path == "/favicon.ico":
                return self._send(204, b"", "image/x-icon")
            if path == "/config.json":
                return self._send(200, json.dumps(srv.config).encode(), "application/json")
            if path == "/" or path == "":
                path = "/index.html"
            return self._file(path)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as e:  # noqa: BLE001
            try:
                self._send(500, str(e).encode(), "text/plain")
            except Exception:  # noqa: BLE001
                pass

    def _file(self, path: str):
        root = WEB_DIR
        for prefix, d in self.server.extra_dirs.items():
            if path.startswith(prefix):
                root, path = d, path[len(prefix) - 1:]
                break
        full = os.path.normpath(os.path.join(root, path.lstrip("/")))
        if not full.startswith(os.path.normpath(root)) or not os.path.isfile(full):
            return self._send(404, b"not found", "text/plain")
        size = os.path.getsize(full)
        ctype = mimetypes.guess_type(full)[0] or "application/octet-stream"
        rng = self.headers.get("Range")
        with open(full, "rb") as fh:
            if rng:
                m = _RANGE.match(rng.strip())
                if not m:
                    return self._send(416, b"", ctype, {"Content-Range": f"bytes */{size}"})
                a, b = m.groups()
                if a == "":
                    start, end = max(0, size - int(b)), size - 1
                else:
                    start = int(a)
                    end = min(int(b), size - 1) if b else size - 1
                if start >= size or start > end:
                    return self._send(416, b"", ctype, {"Content-Range": f"bytes */{size}"})
                fh.seek(start)
                body = fh.read(end - start + 1)
                return self._send(206, body, ctype, {"Content-Range": f"bytes {start}-{end}/{size}",
                                                     "Accept-Ranges": "bytes"})
            return self._send(200, fh.read(), ctype, {"Accept-Ranges": "bytes"})


class _Server(ThreadingHTTPServer):
    daemon_threads = True

    def handle_error(self, request, client_address):
        import sys
        exc = sys.exc_info()[1]
        if isinstance(exc, (ConnectionAbortedError, ConnectionResetError, BrokenPipeError, TimeoutError)):
            return  # the browser closed a keep-alive connection: harmless
        super().handle_error(request, client_address)


class RenderServer:
    def __init__(self, tiles=None, glyphs=None, config: dict | None = None,
                 extra_dirs: dict[str, str] | None = None, port: int = 0):
        from .glyphs import GlyphMaker
        self.httpd = _Server(("127.0.0.1", port), _Handler)
        self.httpd.tiles = tiles
        self.httpd.glyphs = glyphs or GlyphMaker()
        self.httpd.config = config or {}
        self.httpd.extra_dirs = extra_dirs or {}
        self._t = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.httpd.server_address[1]}"

    @property
    def config(self) -> dict:
        return self.httpd.config

    def start(self):
        self._t.start()
        return self

    def stop(self):
        self.httpd.shutdown()
        self.httpd.server_close()

    def __enter__(self):
        return self.start()

    def __exit__(self, *exc):
        self.stop()
