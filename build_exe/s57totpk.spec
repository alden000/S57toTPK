# PyInstaller spec: one-file portable executable.
#   pyinstaller --noconfirm build_exe/s57totpk.spec
# On Windows the result is dist/s57totpk.exe. It renders with the installed
# Microsoft Edge, so no browser is bundled; Playwright's driver is.
import os
from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, collect_submodules

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))

datas = [(os.path.join(ROOT, "s57totpk", "web"), "s57totpk/web")]
datas += collect_data_files("pyogrio")          # gdal_data (S-57 object/attribute CSVs), proj_data
datas += collect_data_files("playwright")       # node driver
binaries = collect_dynamic_libs("pyogrio") + collect_dynamic_libs("shapely")
hidden = collect_submodules("pyogrio") + collect_submodules("playwright") + ["PIL.WebPImagePlugin"]

a = Analysis(
    [os.path.join(ROOT, "build_exe", "entry.py")],
    pathex=[ROOT],
    binaries=binaries,
    datas=datas,
    hiddenimports=hidden,
    excludes=["matplotlib", "pandas", "geopandas", "scipy", "IPython", "pytest", "rasterio"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, a.binaries, a.datas, [],
    name="s57totpk",
    console=True,          # CLI; a double-click opens the GUI and hides the console
    upx=False,
    icon=None,
)
