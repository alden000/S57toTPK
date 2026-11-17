# s57totpk — S-57 ENC → ArcGIS tile package

Turns a folder of S-57 ENC cells (an `ENC_ROOT` exchange set: `.000` base cells
plus `.001`, `.002` … updates) into an ArcGIS tile package (`.tpkx` and/or
`.tpk`). The chart is drawn in S-52-style nautical symbology for offline use in
ArcGIS apps. Input must be plain (unencrypted) S-57.

It runs as a single portable Windows program (`s57totpk.exe`). Double-click
it to use the window; there is also a command line for scripting.

## Using it (no command line needed)

1. Double-click **s57totpk.exe**. A window opens.
2. **Charts folder**: click *Browse…* and pick the `ENC_ROOT` folder of
   your chart exchange set, the folder that holds one sub-folder per chart.
   The window confirms how many charts it found.
3. **Where to save**: pick a folder for the result, and give the package a
   name.
4. **How much detail**:
   * *Overview*: the whole area down to about 1:72,000. Small and quick.
   * *Standard (recommended)*: down to about 1:9,000.
   * *Maximum*: down to about 1:4,500. Big areas can take many hours.
   * *Custom*: pick the zoom levels yourself; the matching scales are shown.
   * *Extra detail in one area*: tick it, click *Choose area on map…*, and
     drag a box around a harbour on the map that opens in your browser. Only
     that box gets the deeper zoom levels, which keeps time and file size
     down.
5. **Colours and package type**: Day / Dusk / Night (one package each), and
   `.tpkx` (current ArcGIS: Pro 2.3+, Field Maps, ArcGIS Online) and/or
   `.tpk` (older ArcGIS apps).
6. Click **Start**. A progress bar shows how far along it is and roughly how
   long is left. You can press **Stop** or close the window at any time.
   Pressing **Start** later continues where it stopped.
7. When it finishes, the window lists the files it made and offers to open
   the folder. In ArcGIS Pro use *Add Data*. For Field Maps, copy the file to
   the device or upload it to ArcGIS Online.

*Preview chart* shows the chart in your web browser before you start, so you
can check how it looks.

The window remembers your choices for next time. *Show advanced settings*
holds the less common options: tile sharpness, image format, the depths used
for safety colouring, which browser to draw with, and how many to run at
once.

### Which browser?

The chart is drawn by a browser running hidden in the background. By default
this is **Microsoft Edge**, which every Windows 10/11 PC has; if Edge is
missing it uses Google Chrome. Any Chromium-based browser works (Edge,
Chrome, Brave, Vivaldi, Opera). Choose *Other…* under Advanced settings and
point it at the browser's `.exe`. Firefox can't do the drawing step. The
*Preview* opens in your normal browser, whichever that is.

## Command line (optional)

```
s57totpk.exe run --enc D:\charts\ENC_ROOT --out D:\charts\work
```

Defaults: zoom 9–16, 512 px (high-DPI) PNG tiles, day colours, `.tpkx`.
Useful options:

```
--minzoom 9 --maxzoom 16                       zoom range
--detail-bbox=-71.45,41.45,-71.30,41.52 --detail-maxzoom 18   deeper zooms over a port only
--schemes day,dusk,night         one package per colour scheme
--package tpkx,tpk               both package types
--tile-size 256                  standard 96 dpi tiles
--format jpeg|mixed              smaller packages (mixed = JPEG where opaque, PNG at chart edges)
--workers 3                      browser processes in parallel (default: auto from CPU count)
--block 4                        smaller render blocks (default 8; uses less memory)
--channel chrome | --browser C:\path\to\browser.exe     which Chromium-based browser draws the tiles
--safety-depth 8 --safety-contour 10 --shallow-contour 2 --deep-contour 30
--detach                         keep running in the background; progress in OUT\s57totpk.log
```

Write a bbox that starts with a minus sign with `=`, as in `--detail-bbox=-71.4,...`.
`s57totpk.exe preview --out D:\charts\work --enc D:\charts\ENC_ROOT` opens
the interactive preview. The charts are re-read automatically when the
`ENC_ROOT` files or the depth settings change.

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

   Speed: each block is rendered once and then cut and PNG-encoded in Web
   Workers inside the page. Parallel work runs in separate browser processes,
   because pages of one browser share a single GPU process. 8×8 blocks keep
   79% of the drawn pixels, against 64% for 4×4. On a 4-core machine with
   software GL this measured 49 ms per 512 px tile, against 72 ms for 4×4
   blocks with one browser. The log shows the WebGL renderer in use; if it
   says SwiftShader, Edge is drawing on the CPU. Resuming needs the same
   `--block` value, because the block grid depends on it.
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
