"""Command line: s57totpk run --enc ENC_ROOT --out WORKDIR [...]

Steps (each can be run on its own; `run` does them all and skips work that
is already done):
  composite  S-57 cells -> enc.geojsons (+ enc_meta.json)
  render     raster tiles per colour scheme -> tiles-<scheme>.mbtiles (resumable)
  package    MBTiles -> .tpkx / .tpk
  preview    interactive map in the browser to check the symbology
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import threading
import time

from . import __version__, s52


class Logger:
    def __init__(self, path: str | None = None):
        self.path = path
        self._lock = threading.Lock()

    def __call__(self, msg: str):
        line = f"{time.strftime('%H:%M:%S')} {msg}"
        with self._lock:
            print(line, flush=True)
            if self.path:
                with open(self.path, "a", encoding="utf-8") as fh:
                    fh.write(line + "\n")


def _bbox(s: str):
    v = [float(x) for x in s.replace(" ", "").split(",")]
    if len(v) != 4 or v[0] >= v[2] or v[1] >= v[3]:
        raise argparse.ArgumentTypeError("bbox must be minlon,minlat,maxlon,maxlat")
    return tuple(v)


def _add_common(p):
    p.add_argument("--out", required=True, help="work/output folder")


def _add_s52(p):
    g = p.add_argument_group("S-52 display settings")
    g.add_argument("--safety-depth", type=float, default=10.0)
    g.add_argument("--shallow-contour", type=float, default=2.0)
    g.add_argument("--safety-contour", type=float, default=10.0)
    g.add_argument("--deep-contour", type=float, default=30.0)
    g.add_argument("--two-shades", action="store_true", help="two depth shades instead of four")
    g.add_argument("--no-labels", action="store_true", help="no names / light descriptions")
    g.add_argument("--keep-attributes", action="store_true", help="keep all S-57 attributes in enc.geojsons")


def _add_render(p):
    g = p.add_argument_group("rendering")
    g.add_argument("--minzoom", type=int, default=9)
    g.add_argument("--maxzoom", type=int, default=16)
    g.add_argument("--detail-bbox", type=_bbox, help="minlon,minlat,maxlon,maxlat for zooms above --maxzoom")
    g.add_argument("--detail-maxzoom", type=int, help="deepest zoom inside --detail-bbox (e.g. 18)")
    g.add_argument("--schemes", default="day", help="comma list of day,dusk,night")
    g.add_argument("--tile-size", type=int, choices=(256, 512), default=512,
                   help="512 = high-DPI tiles (192 dpi), 256 = standard 96 dpi")
    g.add_argument("--workers", type=int, default=2, help="browser pages rendering in parallel")
    g.add_argument("--staging", choices=("png", "webp"), default="png", help="staging tile format (lossless)")
    g.add_argument("--tiler", choices=("builtin", "tippecanoe"), default="builtin",
                   help="vector tiles: built-in (no extra software) or tippecanoe in Docker")
    g.add_argument("--vector-maxzoom", type=int, default=16, help="deepest vector tile zoom")
    g.add_argument("--browser", help="path to msedge.exe / chrome (default: installed Edge)")
    g.add_argument("--channel", help="Playwright browser channel, e.g. msedge, chrome")


def _add_package(p):
    g = p.add_argument_group("packaging")
    g.add_argument("--name", default="ENC", help="package name / file name prefix")
    g.add_argument("--package", default="tpkx", help="comma list of tpkx,tpk")
    g.add_argument("--format", choices=("png", "jpeg", "mixed"), default="png", help="tile image format in the package")
    g.add_argument("--jpeg-quality", type=int, default=90)
    g.add_argument("--png-colors", type=int, default=0, help="quantize PNG to N colours (0 = off)")
    g.add_argument("--tpk-storage", choices=("v1", "v2"), default="v1", help="bundle format inside .tpk")
    g.add_argument("--description", default="")


def build_parser():
    ap = argparse.ArgumentParser(prog="s57totpk", description="S-57 ENC -> ArcGIS tile package (.tpkx/.tpk)")
    ap.add_argument("--version", action="version", version=__version__)
    sub = ap.add_subparsers(dest="cmd")

    p = sub.add_parser("run", help="all steps")
    p.add_argument("--enc", required=True, help="ENC_ROOT folder (S-57 .000 + updates)")
    _add_common(p); _add_s52(p); _add_render(p); _add_package(p)
    p.add_argument("--recomposite", action="store_true", help="redo the composite even if it exists")
    p.add_argument("--sliver-width", type=float, default=200.0, help="max width (m) of gaps filled between cells")
    p.add_argument("--detach", action="store_true", help="run in a detached background process (log in OUT/s57totpk.log)")

    p = sub.add_parser("composite", help="S-57 -> enc.geojsons")
    p.add_argument("--enc", required=True)
    _add_common(p); _add_s52(p)
    p.add_argument("--sliver-width", type=float, default=200.0)

    p = sub.add_parser("render", help="enc.geojsons -> tiles-<scheme>.mbtiles")
    _add_common(p); _add_render(p)
    p.add_argument("--detach", action="store_true")

    p = sub.add_parser("package", help="tiles-<scheme>.mbtiles -> .tpkx/.tpk")
    _add_common(p); _add_package(p)
    p.add_argument("--schemes", default="day")
    p.add_argument("--mbtiles", help="package this MBTiles file instead")

    p = sub.add_parser("preview", help="open the chart in an interactive browser map")
    _add_common(p)
    p.add_argument("--scheme", default="day")
    p.add_argument("--port", type=int, default=0)
    p.add_argument("--no-open", action="store_true")
    p.add_argument("--vector-maxzoom", type=int, default=16)

    p = sub.add_parser("inspect", help="summarise a .tpkx/.tpk/.mbtiles")
    p.add_argument("file")
    return ap


def _params(a) -> s52.S52Params:
    return s52.S52Params(safety_depth=a.safety_depth, shallow_contour=a.shallow_contour,
                         safety_contour=a.safety_contour, deep_contour=a.deep_contour,
                         two_shades=a.two_shades, labels=not a.no_labels)


def _schemes(s: str):
    out = [x.strip().lower() for x in s.split(",") if x.strip()]
    bad = [x for x in out if x not in s52.SCHEMES]
    if bad:
        raise SystemExit(f"unknown colour scheme(s): {', '.join(bad)}")
    return out


def do_composite(a, log):
    from .composite import build
    return build(a.enc, a.out, _params(a), sliver_max_width_m=a.sliver_width,
                 keep_all_attributes=a.keep_attributes, log=log)


def open_tiles(a, log):
    out = a.out
    if getattr(a, "tiler", "builtin") == "tippecanoe":
        from .tippecanoe import make_tiles
        from .vtiles import MBTilesSource
        path = os.path.join(out, "enc-tippecanoe.mbtiles")
        src = os.path.join(out, "enc.geojsons")
        if not os.path.exists(path) or os.path.getmtime(path) < os.path.getmtime(src):
            make_tiles(out, maxzoom=a.vector_maxzoom, log=log)
        return MBTilesSource(path)
    from .vtiles import VectorTiler
    return VectorTiler(os.path.join(out, "enc.geojsons"), maxzoom=a.vector_maxzoom,
                       cache_path=os.path.join(out, "vector-cache.mbtiles"), log=log)


def do_render(a, log):
    from .composite import load_meta
    from .render import RenderOptions, render
    meta = load_meta(a.out)
    tiles = open_tiles(a, log)
    if a.detail_maxzoom and not a.detail_bbox:
        raise SystemExit("--detail-maxzoom needs --detail-bbox")
    paths = []
    try:
        for scheme in _schemes(a.schemes):
            opts = RenderOptions(minzoom=a.minzoom, maxzoom=a.maxzoom, detail_bbox=a.detail_bbox,
                                 detail_maxzoom=a.detail_maxzoom, tile_size=a.tile_size, scheme=scheme,
                                 workers=a.workers, staging_format=a.staging, browser_path=a.browser,
                                 browser_channel=a.channel, vmaxzoom=tiles.maxzoom)
            paths.append(render(os.path.join(a.out, f"tiles-{scheme}.mbtiles"), meta, tiles, opts, log=log))
    finally:
        if hasattr(tiles, "close"):
            tiles.close()
    return paths


def do_package(a, log, mbtiles_paths=None):
    from .package import PackageOptions, write_package
    if getattr(a, "mbtiles", None):
        mbtiles_paths = [a.mbtiles]
    if mbtiles_paths is None:
        mbtiles_paths = [os.path.join(a.out, f"tiles-{s}.mbtiles") for s in _schemes(a.schemes)]
    kinds = [k.strip().lower() for k in a.package.split(",") if k.strip()]
    outs = []
    for mb in mbtiles_paths:
        if not os.path.exists(mb):
            raise SystemExit(f"{mb} not found (render first)")
        stem = os.path.splitext(os.path.basename(mb))[0].replace("tiles-", "")
        name = f"{a.name}-{stem}" if len(mbtiles_paths) > 1 or stem != "day" else a.name
        opts = PackageOptions(name=name, fmt=a.format, jpeg_quality=a.jpeg_quality, png_colors=a.png_colors,
                              tpk_storage=a.tpk_storage, description=a.description)
        for k in kinds:
            if k not in ("tpk", "tpkx"):
                raise SystemExit(f"unknown package type {k}")
            outs.append(write_package(mb, os.path.join(a.out, f"{name}.{k}"), opts, log=log))
    return outs


def do_preview(a, log):
    import webbrowser
    from .composite import load_meta
    from .render import RenderOptions, page_config
    from .server import RenderServer
    meta = load_meta(a.out)
    a.tiler = "builtin"
    tiles = open_tiles(a, log)
    cfg = page_config(meta, RenderOptions(scheme=a.scheme, vmaxzoom=tiles.maxzoom))
    srv = RenderServer(tiles=tiles, config=cfg, port=a.port).start()
    url = f"{srv.url}/index.html?preview&scheme={a.scheme}"
    log(f"Preview at {url}  (Ctrl+C to stop)")
    if not a.no_open:
        webbrowser.open(url)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        srv.stop()


def do_inspect(a, log):
    import zipfile
    f = a.file
    if f.lower().endswith(".mbtiles"):
        from .mbtiles import MBTilesReader
        r = MBTilesReader(f)
        log(f"{f}: {r.count()} tiles, zooms {r.zooms()}, metadata {r.meta}")
        return
    with zipfile.ZipFile(f) as zf:
        names = zf.namelist()
        bundles = [n for n in names if n.endswith(".bundle")]
        levels = sorted({n.split("/")[-2] for n in bundles})
        log(f"{f}: {len(names)} entries, {len(bundles)} bundles, levels {', '.join(levels)}")
        for n in ("root.json", "v101/Layers/conf.xml"):
            if n in names:
                log(f"{n}: {zf.read(n)[:400].decode('utf-8', 'replace')} ...")


def _detach(argv, out, log):
    args = [a for a in argv if a != "--detach"]
    exe = [sys.executable] if getattr(sys, "frozen", False) else [sys.executable, "-m", "s57totpk"]
    logf = open(os.path.join(out, "s57totpk.log"), "ab")
    kw = {}
    if sys.platform == "win32":
        kw["creationflags"] = 0x00000008 | 0x00000200 | 0x08000000  # DETACHED | NEW_GROUP | NO_WINDOW
    else:
        kw["start_new_session"] = True
    p = subprocess.Popen(exe + args, stdout=logf, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, **kw)
    log(f"Started in background (pid {p.pid}); progress: {os.path.join(out, 's57totpk.log')}")


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        from .gui import main as gui_main
        return gui_main()
    a = build_parser().parse_args(argv)
    if not a.cmd:
        build_parser().print_help()
        return 2
    if a.cmd == "inspect":
        return do_inspect(a, Logger()) or 0
    os.makedirs(a.out, exist_ok=True)
    if getattr(a, "detach", False):
        _detach(argv, a.out, Logger())
        return 0
    log = Logger(os.path.join(a.out, "s57totpk.log"))
    t0 = time.time()
    if a.cmd == "composite":
        do_composite(a, log)
    elif a.cmd == "render":
        do_render(a, log)
    elif a.cmd == "package":
        do_package(a, log)
    elif a.cmd == "preview":
        do_preview(a, log)
    elif a.cmd == "run":
        if a.recomposite or not os.path.exists(os.path.join(a.out, "enc_meta.json")):
            do_composite(a, log)
        else:
            log("Composite exists (use --recomposite to redo)")
        paths = do_render(a, log)
        do_package(a, log, paths)
        log(f"All done in {(time.time() - t0) / 60:.1f} min")
    return 0
