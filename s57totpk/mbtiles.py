"""MBTiles (SQLite) staging for rendered raster tiles, with resume support.

Writes go to ``<path>.partial``; a ``blocks`` table records which render
blocks are complete so an interrupted run picks up where it stopped. When
every block is done the file is renamed to ``<path>``.
"""
from __future__ import annotations

import json
import os
import sqlite3


class StagingMBTiles:
    def __init__(self, path: str, fingerprint: dict, log=print):
        self.path = path
        self.partial = path + ".partial"
        self.log = log
        fp = json.dumps(fingerprint, sort_keys=True)
        if os.path.exists(path) and not os.path.exists(self.partial):
            # finished earlier: reopen as partial only if settings changed
            if _read_meta(path).get("s57totpk_fingerprint") == fp:
                self.complete = True
                self.db = None
                return
            log(f"  {os.path.basename(path)} exists with other settings; re-rendering")
            os.replace(path, self.partial)
        self.complete = False
        self.db = sqlite3.connect(self.partial, isolation_level=None)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=NORMAL")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS metadata (name TEXT PRIMARY KEY, value TEXT);
            CREATE TABLE IF NOT EXISTS tiles (zoom_level INTEGER, tile_column INTEGER, tile_row INTEGER,
                tile_data BLOB, PRIMARY KEY (zoom_level, tile_column, tile_row));
            CREATE TABLE IF NOT EXISTS blocks (z INTEGER, bx INTEGER, by INTEGER, PRIMARY KEY (z, bx, by));
        """)
        row = self.db.execute("SELECT value FROM metadata WHERE name='s57totpk_fingerprint'").fetchone()
        if row and row[0] != fp:
            log("  staging file was made with other settings; starting over")
            self.db.executescript("DELETE FROM tiles; DELETE FROM blocks;")
        self.db.execute("INSERT OR REPLACE INTO metadata VALUES ('s57totpk_fingerprint', ?)", (fp,))

    def set_metadata(self, md: dict):
        for k, v in md.items():
            self.db.execute("INSERT OR REPLACE INTO metadata VALUES (?, ?)", (k, str(v)))

    def done_blocks(self) -> set:
        return {tuple(r) for r in self.db.execute("SELECT z, bx, by FROM blocks")}

    def write_block(self, z: int, bx: int, by: int, tiles: list[tuple[int, int, bytes]]):
        """tiles: (x, y, data) in XYZ scheme. One transaction per block."""
        n = 1 << z
        self.db.execute("BEGIN")
        try:
            self.db.executemany("INSERT OR REPLACE INTO tiles VALUES (?, ?, ?, ?)",
                                [(z, x, n - 1 - y, d) for x, y, d in tiles])
            self.db.execute("INSERT OR REPLACE INTO blocks VALUES (?, ?, ?)", (z, bx, by))
            self.db.execute("COMMIT")
        except Exception:
            self.db.execute("ROLLBACK")
            raise

    def finish(self):
        self.db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        self.db.execute("PRAGMA journal_mode=DELETE")
        self.db.close()
        self.db = None
        os.replace(self.partial, self.path)
        self.complete = True

    def close(self):
        if self.db is not None:
            self.db.close()
            self.db = None


def _read_meta(path: str) -> dict:
    try:
        db = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            return dict(db.execute("SELECT name, value FROM metadata").fetchall())
        finally:
            db.close()
    except sqlite3.Error:
        return {}


class MBTilesReader:
    def __init__(self, path: str):
        self.db = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        self.meta = dict(self.db.execute("SELECT name, value FROM metadata").fetchall())

    def zooms(self) -> list[int]:
        return [r[0] for r in self.db.execute("SELECT DISTINCT zoom_level FROM tiles ORDER BY zoom_level")]

    def count(self) -> int:
        return self.db.execute("SELECT COUNT(*) FROM tiles").fetchone()[0]

    def tiles_xyz(self, z: int):
        """(x, y_xyz) for every tile at zoom z."""
        n = 1 << z
        for x, row in self.db.execute("SELECT tile_column, tile_row FROM tiles WHERE zoom_level=?", (z,)):
            yield x, n - 1 - row

    def get(self, z: int, x: int, y: int) -> bytes | None:
        r = self.db.execute("SELECT tile_data FROM tiles WHERE zoom_level=? AND tile_column=? AND tile_row=?",
                            (z, x, (1 << z) - 1 - y)).fetchone()
        return r[0] if r else None

    def region(self, z: int, x0: int, x1: int, y0: int, y1: int):
        """Tiles with x0<=x<=x1, y0<=y<=y1 (XYZ) -> iterator of (x, y, data)."""
        n = 1 << z
        q = ("SELECT tile_column, tile_row, tile_data FROM tiles WHERE zoom_level=? AND tile_column BETWEEN ? AND ? "
             "AND tile_row BETWEEN ? AND ?")
        for x, row, d in self.db.execute(q, (z, x0, x1, n - 1 - y1, n - 1 - y0)):
            yield x, n - 1 - row, d

    def close(self):
        self.db.close()
