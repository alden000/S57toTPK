"""Discover S-57 cells in an exchange set and stage them for GDAL.

* Every ``XXXXXXXX.000`` found anywhere under the input folder is a candidate
  base cell; when the same cell appears more than once the highest edition
  (then the highest re-issue update number, then the latest issue date) wins.
* Update files (``.001`` ...) are matched to the chosen base by edition and
  update number, wherever they sit in the tree, and copied beside the base
  as a consecutive ``.001``, ``.002`` ... sequence (GDAL's S-57 reader only
  looks for consecutive extensions starting at ``.001``).
* A cancellation update (EDTN = 0) for the chosen edition drops the cell.
"""
from __future__ import annotations

import os
import re
import shutil
from dataclasses import dataclass, field

from .iso8211 import DatasetHeader, read_header

_NAME_RE = re.compile(r"^([A-Za-z0-9_]{8})\.(\d{3})$")


@dataclass
class Cell:
    name: str
    base: str
    header: DatasetHeader
    updates: list[str] = field(default_factory=list)   # in apply order
    last_updn: int = 0
    warnings: list[str] = field(default_factory=list)
    staged: str | None = None

    @property
    def scale(self) -> int:
        return self.header.cscl or 0

    @property
    def edition(self) -> int:
        return self.header.edtn


def discover(root: str, log=print) -> list[Cell]:
    bases: dict[str, list[tuple[str, DatasetHeader]]] = {}
    updates: dict[str, list[tuple[str, DatasetHeader]]] = {}
    for dirpath, _dirs, files in os.walk(root):
        for fn in files:
            m = _NAME_RE.match(fn)
            if not m:
                continue
            name, ext = m.group(1).upper(), int(m.group(2))
            path = os.path.join(dirpath, fn)
            try:
                hdr = read_header(path)
            except Exception as e:  # noqa: BLE001 - report and carry on
                log(f"  skip {path}: {e}")
                continue
            (bases if ext == 0 else updates).setdefault(name, []).append((path, hdr))

    cells: list[Cell] = []
    for name in sorted(bases):
        cands = sorted(bases[name], key=lambda t: (t[1].edtn, t[1].updn, t[1].isdt))
        path, hdr = cands[-1]
        cell = Cell(name=name, base=path, header=hdr, last_updn=hdr.updn)
        ups = updates.get(name, [])
        cancelled = [p for p, h in ups if h.edtn == 0 and h.isdt >= hdr.isdt]
        if cancelled:
            log(f"  {name}: cancelled by {os.path.basename(cancelled[0])}, skipped")
            continue
        by_updn: dict[int, tuple[str, DatasetHeader]] = {}
        for p, h in ups:
            if h.edtn != hdr.edtn or h.updn <= hdr.updn:
                continue
            if h.updn not in by_updn or h.isdt > by_updn[h.updn][1].isdt:
                by_updn[h.updn] = (p, h)
        n = hdr.updn + 1
        while n in by_updn:
            cell.updates.append(by_updn[n][0])
            cell.last_updn = n
            n += 1
        skipped = sorted(u for u in by_updn if u >= n)
        if skipped:
            cell.warnings.append(
                f"update {n:03d} missing; later updates {', '.join(f'{u:03d}' for u in skipped)} not applied")
        cells.append(cell)
    return cells


def stage(cells: list[Cell], work_dir: str) -> None:
    """Copy each base and its update sequence into ``work_dir/<NAME>/``."""
    for c in cells:
        d = os.path.join(work_dir, c.name)
        os.makedirs(d, exist_ok=True)
        dst = os.path.join(d, c.name + ".000")
        _copy_if_changed(c.base, dst)
        for i, u in enumerate(c.updates, start=1):
            _copy_if_changed(u, os.path.join(d, f"{c.name}.{i:03d}"))
        # remove stale updates from a previous run
        i = len(c.updates) + 1
        while os.path.exists(os.path.join(d, f"{c.name}.{i:03d}")):
            os.remove(os.path.join(d, f"{c.name}.{i:03d}"))
            i += 1
        c.staged = dst


def _copy_if_changed(src: str, dst: str) -> None:
    try:
        s, d = os.stat(src), os.stat(dst)
        if s.st_size == d.st_size and int(s.st_mtime) == int(d.st_mtime):
            return
    except FileNotFoundError:
        pass
    shutil.copy2(src, dst)
