"""Draw raster tiles with MapLibre GL in a headless browser.

Blocks of BLOCK x BLOCK tiles are rendered in one view with a MARGIN of
extra map around them; the margin is cropped so labels at block edges stay
whole. Tiles are staged in an MBTiles file with resume support.
"""
from __future__ import annotations

import asyncio
import base64
import io
import math
import os
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field, asdict

import shapely

from . import s52
from .mbtiles import StagingMBTiles


@dataclass
class RenderOptions:
    minzoom: int = 9
    maxzoom: int = 16
    detail_bbox: tuple | None = None        # (minlon, minlat, maxlon, maxlat)
    detail_maxzoom: int | None = None       # zooms maxzoom+1..detail_maxzoom only inside detail_bbox
    tile_size: int = 512                    # 256 (96 dpi) or 512 (high-DPI, 192 dpi)
    scheme: str = "day"
    block: int = 4
    margin: int = 128                       # CSS px around each block
    workers: int = 2                        # browser pages rendering in parallel
    staging_format: str = "png"             # png | webp (lossless)
    browser_path: str | None = None
    browser_channel: str | None = None
    vmaxzoom: int = 15                      # vector source max zoom (MapLibre zoom)
    extra: dict = field(default_factory=dict)

    @property
    def ratio(self) -> int:
        return max(1, self.tile_size // 256)

    @property
    def top_zoom(self) -> int:
        return max(self.maxzoom, self.detail_maxzoom or 0)


def lonlat_to_tile(lon, lat, z):
    n = 1 << z
    lat = max(min(lat, 85.0511287798), -85.0511287798)
    x = (lon + 180.0) / 360.0 * n
    y = (1.0 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2.0 * n
    return x, y


def tile_to_lonlat(x, y, z):
    n = 1 << z
    lon = x / n * 360.0 - 180.0
    lat = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y / n))))
    return lon, lat


def plan_blocks(coverage, opts: RenderOptions) -> list[tuple[int, int, int]]:
    """All (z, bx, by) blocks to render, low zooms first."""
    shapely.prepare(coverage)
    B = opts.block
    out = []
    detail = shapely.box(*opts.detail_bbox) if opts.detail_bbox else None
    for z in range(opts.minzoom, opts.top_zoom + 1):
        if z > opts.maxzoom:
            if detail is None:
                break
            region = shapely.intersection(coverage, detail)
        else:
            region = coverage
        if region.is_empty:
            continue
        shapely.prepare(region)
        minx, miny, maxx, maxy = region.bounds
        x0, y1 = lonlat_to_tile(minx, miny, z)
        x1, y0 = lonlat_to_tile(maxx, maxy, z)
        n = 1 << z
        bx0, bx1 = int(x0) // B, min(int(x1), n - 1) // B
        by0, by1 = int(y0) // B, min(int(y1), n - 1) // B
        for by in range(by0, by1 + 1):
            for bx in range(bx0, bx1 + 1):
                lon0, lat1 = tile_to_lonlat(bx * B, by * B, z)
                lon1, lat0 = tile_to_lonlat(min((bx + 1) * B, n), min((by + 1) * B, n), z)
                if region.intersects(shapely.box(lon0, lat0, lon1, lat1)):
                    out.append((z, bx, by))
    return out


def _split_block(png: bytes, opts: RenderOptions, z: int, bx: int, by: int):
    from PIL import Image
    im = Image.open(io.BytesIO(png))
    im.load()
    if im.mode != "RGBA":
        im = im.convert("RGBA")
    r = opts.ratio
    m = opts.margin * r
    ts = opts.tile_size
    n = 1 << z
    out = []
    for j in range(opts.block):
        for i in range(opts.block):
            x, y = bx * opts.block + i, by * opts.block + j
            if x >= n or y >= n:
                continue
            t = im.crop((m + i * ts, m + j * ts, m + (i + 1) * ts, m + (j + 1) * ts))
            if t.getchannel("A").getextrema()[1] == 0:
                continue  # fully transparent: outside the chart
            buf = io.BytesIO()
            if opts.staging_format == "webp":
                t.save(buf, "WEBP", lossless=True, quality=80, method=4)
            else:
                t.save(buf, "PNG", compress_level=6)
            out.append((x, y, buf.getvalue()))
    return out


def page_config(meta: dict, opts: RenderOptions) -> dict:
    return {
        "scheme": opts.scheme,
        "palette": s52.palette_hex(opts.scheme),
        "palettes": {s: s52.palette_hex(s) for s in s52.SCHEMES},
        "bounds": meta.get("bounds"),
        "vmaxzoom": opts.vmaxzoom,
        "pixelRatio": opts.ratio,
    }


def render(out_path: str, meta: dict, tiles, opts: RenderOptions, log=print, stop_event=None) -> str:
    """Render all blocks into an MBTiles file at out_path. Returns out_path."""
    return asyncio.run(_render(out_path, meta, tiles, opts, log, stop_event))


async def _render(out_path, meta, tiles, opts: RenderOptions, log, stop_event):
    from playwright.async_api import async_playwright
    from .browser import launch
    from .server import RenderServer

    coverage = shapely.from_geojson(__import__("json").dumps(meta["coverage"]))
    blocks = plan_blocks(coverage, opts)
    fp = {"composite": meta.get("created"), "params": meta.get("params"),
          **{k: v for k, v in asdict(opts).items() if k not in ("workers", "browser_path", "browser_channel", "extra")}}
    st = StagingMBTiles(out_path, fp, log=log)
    if st.complete:
        log(f"  {os.path.basename(out_path)} already complete")
        return out_path
    done = st.done_blocks()
    todo = [b for b in blocks if b not in done]
    log(f"Render {opts.scheme}: zoom {opts.minzoom}-{opts.top_zoom}, {opts.tile_size} px tiles, "
        f"{len(blocks)} blocks ({len(done)} done, {len(todo)} to do)")
    st.set_metadata({
        "name": f"ENC {opts.scheme}", "format": opts.staging_format, "type": "baselayer",
        "minzoom": opts.minzoom, "maxzoom": opts.top_zoom, "tile_size": opts.tile_size,
        "bounds": ",".join(f"{v:.6f}" for v in meta["bounds"]), "scheme": opts.scheme,
    })
    if not todo:
        st.finish()
        return out_path

    cfg = page_config(meta, opts)
    view = opts.block * 256 + 2 * opts.margin
    pool = ThreadPoolExecutor(max_workers=max(2, opts.workers))
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue()
    for b in todo:
        queue.put_nowait(b)
    t0 = time.time()
    stats = {"blocks": 0, "tiles": 0}
    total = len(todo)

    with RenderServer(tiles=tiles, config=cfg) as srv:
        async with async_playwright() as pw:
            browser = await launch(pw, opts.browser_path, opts.browser_channel, log=log)
            ctx = await browser.new_context(viewport={"width": view, "height": view},
                                            device_scale_factor=opts.ratio)

            async def new_page():
                page = await ctx.new_page()
                page.on("console", lambda m: m.type == "error" and log(f"  [page] {m.text}"))
                await page.goto(srv.url + "/index.html")
                await page.wait_for_function("window.ready === true || window.lastError", timeout=120_000)
                err = await page.evaluate("window.lastError || null")
                if err:
                    raise RuntimeError(f"render page failed: {err}")
                return page

            async def worker(wid):
                page = await new_page()
                while not queue.empty():
                    if stop_event is not None and stop_event.is_set():
                        return
                    z, bx, by = queue.get_nowait()
                    cx = (bx * opts.block + opts.block / 2)
                    cy = (by * opts.block + opts.block / 2)
                    lon, lat = tile_to_lonlat(cx, cy, z)
                    for attempt in range(3):
                        try:
                            url = await page.evaluate("([a,b,c]) => window.renderView(a,b,c)", [lon, lat, z - 1])
                            break
                        except Exception as e:  # noqa: BLE001 - page crash / timeout: reload
                            log(f"  block z{z} {bx},{by}: {str(e).splitlines()[0]} (retry {attempt + 1})")
                            try:
                                await page.close()
                            except Exception:  # noqa: BLE001
                                pass
                            page = await new_page()
                    else:
                        raise RuntimeError(f"block z{z} {bx},{by} failed 3 times")
                    png = base64.b64decode(url.split(",", 1)[1])
                    res = await loop.run_in_executor(pool, _split_block, png, opts, z, bx, by)
                    st.write_block(z, bx, by, res)
                    stats["blocks"] += 1
                    stats["tiles"] += len(res)
                    nb = stats["blocks"]
                    if nb == 1 or nb % 25 == 0 or nb == total:
                        el = time.time() - t0
                        eta = el / nb * (total - nb)
                        log(f"  {nb}/{total} blocks (z{z}), {stats['tiles']} tiles, "
                            f"{el / 60:.1f} min, ETA {eta / 60:.1f} min")

            try:
                await asyncio.gather(*(worker(i) for i in range(max(1, opts.workers))))
            finally:
                await browser.close()
    pool.shutdown()
    if stop_event is not None and stop_event.is_set():
        st.close()
        log("  stopped; run again to resume")
        return out_path
    remaining = [b for b in blocks if b not in st.done_blocks()]
    if remaining:
        st.close()
        raise RuntimeError(f"{len(remaining)} blocks not rendered; run again to resume")
    st.finish()
    log(f"Render {opts.scheme} done: {stats['tiles']} new tiles in {(time.time() - t0) / 60:.1f} min -> {out_path}")
    return out_path
