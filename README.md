# s57totpk — S-57 ENC → ArcGIS tile package

Turns a folder of S-57 ENC cells (an `ENC_ROOT` exchange set: `.000` base cells
plus `.001`, `.002` … updates) into an ArcGIS tile package (`.tpkx` and/or
`.tpk`). The chart is drawn in S-52-style nautical symbology for offline use in
ArcGIS apps. Input must be plain (unencrypted) S-57.

It runs as a single portable Windows program (`s57totpk.exe`). Start it without
arguments to get a small window, or use the command line.

## Quick start (Windows)

```
s57totpk.exe run --enc D:\charts\ENC_ROOT --out D:\charts\work
```

This writes `D:\charts\work\ENC.tpkx`. It covers zoom 9–16 at 512 px
(high-DPI) PNG tiles in the day colours. Some common options:

```
--detail-bbox=-71.45,41.45,-71.30,41.52 --detail-maxzoom 18   deeper zooms over a port only
--schemes day,dusk,night         one package per colour scheme
--package tpkx,tpk               both package types
--tile-size 256                  standard 96 dpi tiles
--format jpeg|mixed              smaller packages (mixed = JPEG where opaque, PNG at chart edges)
--workers 3                      browser pages rendering in parallel
--safety-depth 8 --safety-contour 10 --shallow-contour 2 --deep-contour 30
--detach                         keep running in the background; progress in OUT\s57totpk.log
```

Use a leading `=` for a bbox that starts with a minus sign (`--detail-bbox=-71.4,...`).

A run you stop or that is interrupted picks up where it stopped. Rendered blocks
are staged in `OUT\tiles-<scheme>.mbtiles.partial`; run the same command again
to continue. For renders that take hours, use `--detach`, or the window's
Run/Stop buttons, so the work is not tied to a console session.

`s57totpk.exe preview --out D:\charts\work` opens the chart as an interactive
map in your browser, so you can check the symbology before a long render.

## Requirements

* Windows 10/11 with Microsoft Edge (already installed on these). Edge draws the
  tiles headless, and nothing else is downloaded.
* Docker is only needed for the optional `--tiler tippecanoe`.

## How it works

1. **Read** (`cells.py`, `composite.py`). The tool finds every cell. When a
   cell appears more than once, it keeps the highest edition. It matches
   updates by edition and update number, copies them beside the `.000` as a
   consecutive `.001…` sequence (GDAL only looks there), and drops cells that
   have a cancellation update. GDAL's S-57 driver (via pyogrio) reads them
   with `RETURN_PRIMITIVES=OFF, RETURN_LINKAGES=OFF, LNAM_REFS=OFF,
   UPDATES=APPLY, SPLIT_MULTIPOINT=ON, ADD_SOUNDG_DEPTH=ON`.
2. **Composite like an ECDIS.** The largest-scale cell wins. Each cell is kept
   only inside its own coverage (M_COVR CATCOV=1, minus CATCOV=2), less what
   larger-scale cells already cover. All geometry operations snap to the S-57
   1e-7° grid, so cell edges match exactly. Areas and lines split at cell
   edges are rejoined. Skin-of-earth gaps between cells (DEPARE, DRGARE,
   LNDARE, UNSARE) are filled from the neighbouring area with the longest
   shared edge, for gaps up to `--sliver-width` metres wide. The S-52
   decisions are made here and stored as short `_xxx` properties: depth
   shades, safety contour, isolated dangers, light descriptions, symbol keys
   and SCAMIN→zoom. Output: `enc.geojsons` (GeoJSONSeq) and `enc_meta.json`.
3. **Vector tiles.** By default a built-in tiler cuts MVT tiles on demand
   while rendering. It simplifies skin-of-earth areas as a coverage, so shared
   borders stay shared, and caches the tiles in `vector-cache.mbtiles`.
   `--tiler tippecanoe` uses tippecanoe 2.79.0 in Docker instead, with
   `-l enc -Z 8 -z 16 -r1 --no-feature-limit --no-tile-size-limit
   --detect-shared-borders --simplification=2`. It tiles inside the container
   to `/tmp` and copies the result out.
4. **Raster tiles** (`render.py`). Rendering uses MapLibre GL 5.24.0 in a
   headless Edge (`--enable-unsafe-swiftshader --ignore-gpu-blocklist`). A
   local server provides byte ranges, tiles and SDF glyphs made from the
   system fonts, so nothing is fetched remotely. Symbols are drawn on the
   device with Canvas 2D. Blocks of 4×4 tiles are rendered with a 128 px
   margin, which is cropped off. Tiles are 512 px at pixelRatio 2 (or 256 px).
   Fully transparent tiles, outside the chart, are skipped.
5. **Package** (`package.py`).
   * `.tpkx`: Esri *tile-package-spec* 1.0. An uncompressed zip with
     `root.json`, `iteminfo.json`, `thumbnail.png` and
     `tile/Lnn/RrrrrCcccc.bundle` (Compact Cache V2, Esri
     *raster-tiles-compactcache*).
   * `.tpk`: `v101/Layers/conf.xml`, `conf.cdi`, `_alllayers/…`,
     `esriinfo/iteminfo.xml`, `item.pkinfo` and
     `servicedescriptions/mapserver/mapserver.json`. Esri documents `.tpk` as
     Compact Cache V1, so V1 (`.bundle` + `.bundlx`) is the default;
     `--tpk-storage v2` writes V2 bundles.
   * The tiling scheme is Web Mercator, WKID 102100/3857, with origin
     (-20037508.342787, 20037508.342787) and the standard ArcGIS Online LOD
     list. For 256 px tiles, resolution(z) = 156543.03392804097 / 2^z at
     96 dpi. 512 px tiles cover the same ground per tile at 192 dpi, so the
     LOD scales are the same.

## Validation done

* `.tpkx` and V2 `.tpk` open with GDAL's ESRIC driver, which implements Esri's
  published Compact Cache V2 and tile-package specs. They give pixel-identical
  results.
* The V1 `.tpk` reads back tile-for-tile with `tpkutils`, a third-party tpk
  reader.
* Bundle headers and indexes are checked against the specs in `tests/`.
* **Not yet opened in an ArcGIS app.** Please open the packages in ArcGIS Pro,
  Field Maps or an ArcGIS Maps SDK app before relying on them.

## Building the exe

On Windows with Python 3.10+: `build_exe\build.cmd` creates `dist\s57totpk.exe`
and runs the tests first. The GitHub workflow `.github/workflows/build-exe.yml`
does the same on a Windows runner. It then smoke-tests the exe with Edge on a
NOAA cell and uploads the exe and sample packages.

From source: `pip install -e .[dev]`, then `python -m s57totpk ...`.

## Tests

`python -m pytest -q tests`. Set `S57TOTPK_TEST_ENC` to an `ENC_ROOT` to also
run the end-to-end test.

## Notes and limits

* The symbology is S-52-*like*, not a certified S-52 presentation library. It
  uses paper-chart style buoys and beacons, S-52 colour tables (the dusk and
  night tables are approximations), depth shading, safety contour, isolated
  dangers, light flares and sectors, soundings with tenths, and the usual
  area boundaries and centred symbols. Object classes without a rule are not
  drawn.
* The safety contour is picked per cell: the shallowest DEPCNT value at or
  deeper than `--safety-contour`.
* Labels collide and declutter per render block.
