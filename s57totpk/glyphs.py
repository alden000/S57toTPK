"""Signed-distance-field glyph PBFs for MapLibre, made locally from a TrueType
font with Pillow (no remote glyph server). Same layout as MapLibre's own
TinySDF path: 24 px font, 3 px buffer, radius 8, cutoff 0.25.
"""
from __future__ import annotations

import os
import sys
import threading

import numpy as np

from . import pbf

FONT_SIZE = 24
BUFFER = 3
RADIUS = 8
CUTOFF = 0.25
GLYPH_TOP_OFFSET = 27   # same convention as MapLibre's local TinySDF glyphs

# font stack name -> candidate files (first existing wins)
_WIN = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")
CANDIDATES = {
    "Regular": [os.path.join(_WIN, "arial.ttf"), os.path.join(_WIN, "segoeui.ttf"),
                "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
                "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                "/System/Library/Fonts/Supplemental/Arial.ttf"],
    "Italic": [os.path.join(_WIN, "ariali.ttf"), os.path.join(_WIN, "segoeuii.ttf"),
               "/usr/share/fonts/truetype/liberation/LiberationSans-Italic.ttf",
               "/usr/share/fonts/truetype/dejavu/DejaVuSans-Oblique.ttf",
               "/System/Library/Fonts/Supplemental/Arial Italic.ttf"],
    "Bold": [os.path.join(_WIN, "arialbd.ttf"), os.path.join(_WIN, "segoeuib.ttf"),
             "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
             "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
             "/System/Library/Fonts/Supplemental/Arial Bold.ttf"],
}


def _edt_sq(f: np.ndarray) -> np.ndarray:
    """Exact squared Euclidean distance transform (brute force; glyph grids
    are tiny). f holds 0 at sources, a large value elsewhere, or a fractional
    squared distance for anti-aliased edge pixels."""
    h, w = f.shape
    ys, xs = np.mgrid[0:h, 0:w]
    src = np.flatnonzero(f < 1e19)
    if len(src) == 0:
        return np.full(f.shape, 1e20)
    sy, sx, sv = ys.flat[src], xs.flat[src], f.flat[src]
    out = np.empty(h * w)
    py, px = ys.ravel(), xs.ravel()
    step = max(1, 200000 // max(len(src), 1))
    for i in range(0, h * w, step):
        d = (py[i:i + step, None] - sy[None]) ** 2 + (px[i:i + step, None] - sx[None]) ** 2 + sv[None]
        out[i:i + step] = d.min(axis=1)
    return out.reshape(h, w)


def sdf(alpha: np.ndarray) -> np.ndarray:
    a = alpha.astype(np.float64) / 255.0
    inf = 1e20
    outer = np.where(a >= 1, 0.0, np.where(a <= 0, inf, np.maximum(0, 0.5 - a) ** 2))
    inner = np.where(a >= 1, inf, np.where(a <= 0, 0.0, np.maximum(0, a - 0.5) ** 2))
    d = np.sqrt(_edt_sq(outer)) - np.sqrt(_edt_sq(inner))
    return np.clip(np.rint(255 - 255 * (d / RADIUS + CUTOFF)), 0, 255).astype(np.uint8)


class GlyphMaker:
    def __init__(self, font_paths: dict[str, str] | None = None):
        self.paths = {}
        for stack, cands in CANDIDATES.items():
            p = (font_paths or {}).get(stack)
            if not p:
                p = next((c for c in cands if os.path.exists(c)), None)
            self.paths[stack] = p
        self._fonts = {}
        self._cache: dict[tuple, bytes] = {}
        self._lock = threading.Lock()

    def _font(self, stack: str):
        from PIL import ImageFont
        if stack not in self._fonts:
            path = self.paths.get(stack) or self.paths.get("Regular")
            if path:
                f = ImageFont.truetype(path, FONT_SIZE)
            else:  # Pillow's bundled scalable font
                f = ImageFont.load_default(FONT_SIZE)
            self._fonts[stack] = f
        return self._fonts[stack]

    def glyph(self, font, ch: str):
        from PIL import Image, ImageDraw
        try:
            l, t, r, b = font.getbbox(ch, anchor="ls")
            adv = font.getlength(ch)
        except Exception:  # noqa: BLE001
            return None
        w, h = max(0, r - l), max(0, b - t)
        out = pbf.f_varint(1, ord(ch))
        if w and h:
            img = Image.new("L", (w + 2 * BUFFER, h + 2 * BUFFER), 0)
            ImageDraw.Draw(img).text((BUFFER - l, BUFFER - t), ch, font=font, fill=255, anchor="ls")
            bmp = sdf(np.asarray(img)).tobytes()
            out += pbf.f_bytes(2, bmp)
        out += (pbf.f_varint(3, w) + pbf.f_varint(4, h) + pbf.f_sint(5, int(l))
                + pbf.f_sint(6, int(-t) - GLYPH_TOP_OFFSET) + pbf.f_varint(7, int(round(adv))))
        return out

    def range_pbf(self, stack: str, start: int) -> bytes:
        stack = stack.split(",")[0].strip()
        if stack not in CANDIDATES:
            stack = "Regular"
        k = (stack, start)
        with self._lock:
            if k in self._cache:
                return self._cache[k]
        font = self._font(stack)
        glyphs = []
        for cp in range(start, start + 256):
            if cp < 32 or 0xD800 <= cp <= 0xDFFF:
                continue
            g = self.glyph(font, chr(cp))
            if g:
                glyphs.append(pbf.f_bytes(3, g))
        body = pbf.f_str(1, stack) + pbf.f_str(2, f"{start}-{start + 255}") + b"".join(glyphs)
        data = pbf.f_bytes(1, body)
        with self._lock:
            self._cache[k] = data
        return data


def describe_fonts(gm: GlyphMaker) -> str:
    return ", ".join(f"{k}={v or 'Pillow default'}" for k, v in gm.paths.items())


if __name__ == "__main__":  # quick manual check
    gm = GlyphMaker()
    print(describe_fonts(gm))
    d = gm.range_pbf("Regular", 0)
    sys.stdout.write(f"{len(d)} bytes\n")
