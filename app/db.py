"""Lop truy cap SQLite. Moi thao tac mo mot ket noi ngan han de an toan da luong."""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Iterable

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;

CREATE TABLE IF NOT EXISTS cameras (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    source      TEXT NOT NULL,
    zone        TEXT NOT NULL DEFAULT 'default',
    enabled     INTEGER NOT NULL DEFAULT 1,
    polygon     TEXT,
    created_at  REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS violations (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    cam_id       TEXT NOT NULL,
    track_id     INTEGER NOT NULL,
    missing      TEXT NOT NULL,
    zone         TEXT NOT NULL,
    ts           REAL NOT NULL,
    image        TEXT,
    clip         TEXT,
    confidence   REAL NOT NULL DEFAULT 0,
    acknowledged INTEGER NOT NULL DEFAULT 0,
    ack_by       TEXT,
    ack_at       REAL
);

CREATE INDEX IF NOT EXISTS idx_violations_ts   ON violations(ts DESC);
CREATE INDEX IF NOT EXISTS idx_violations_cam  ON violations(cam_id, ts DESC);
CREATE INDEX IF NOT EXISTS idx_violations_ack  ON violations(acknowledged, ts DESC);

CREATE TABLE IF NOT EXISTS events (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    ts      REAL NOT NULL,
    level   TEXT NOT NULL,
    cam_id  TEXT,
    message TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_events_ts ON events(ts DESC);

CREATE TABLE IF NOT EXISTS camera_status (
    cam_id       TEXT PRIMARY KEY,
    online       INTEGER NOT NULL DEFAULT 0,
    fps          REAL NOT NULL DEFAULT 0,
    latency_ms   REAL NOT NULL DEFAULT 0,
    persons      INTEGER NOT NULL DEFAULT 0,
    last_frame   REAL NOT NULL DEFAULT 0,
    last_error   TEXT
);
"""


class Database:
    def __init__(self, path: str | Path):
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        with self._conn() as con:
            con.executescript(SCHEMA)

    def _conn(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.path, timeout=15.0, check_same_thread=False)
        con.row_factory = sqlite3.Row
        return con

    def _write(self, sql: str, args: Iterable[Any] = ()) -> int:
        with self._lock:
            con = self._conn()
            try:
                cur = con.execute(sql, tuple(args))
                con.commit()
                return int(cur.lastrowid or 0)
            finally:
                con.close()

    def _rows(self, sql: str, args: Iterable[Any] = ()) -> list[dict]:
        con = self._conn()
        try:
            return [dict(r) for r in con.execute(sql, tuple(args)).fetchall()]
        finally:
            con.close()

    # ---------------- cameras ----------------
    def upsert_camera(self, cam: dict) -> None:
        self._write(
            """INSERT INTO cameras (id, name, source, zone, enabled, polygon, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET
                 name=excluded.name,
                 source=excluded.source,
                 zone=excluded.zone,
                 enabled=excluded.enabled,
                 polygon=excluded.polygon""",
            (
                cam["id"],
                cam.get("name", cam["id"]),
                cam.get("source", cam["id"]),
                cam.get("zone", "default"),
                1 if cam.get("enabled", True) else 0,
                json.dumps(cam["polygon"]) if cam.get("polygon") else None,
                time.time(),
            ),
        )

    def list_cameras(self, enabled_only: bool = False) -> list[dict]:
        sql = "SELECT * FROM cameras"
        if enabled_only:
            sql += " WHERE enabled = 1"
        sql += " ORDER BY id"
        rows = self._rows(sql)
        for r in rows:
            r["enabled"] = bool(r["enabled"])
            r["polygon"] = json.loads(r["polygon"]) if r["polygon"] else None
        return rows

    def delete_camera(self, cam_id: str) -> None:
        self._write("DELETE FROM cameras WHERE id = ?", (cam_id,))
        self._write("DELETE FROM camera_status WHERE cam_id = ?", (cam_id,))

    # ---------------- violations ----------------
    def add_violation(
        self,
        cam_id: str,
        track_id: int,
        missing: list[str],
        zone: str,
        ts: float,
        image: str | None,
        clip: str | None,
        confidence: float,
    ) -> int:
        return self._write(
            """INSERT INTO violations
               (cam_id, track_id, missing, zone, ts, image, clip, confidence)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (cam_id, track_id, json.dumps(missing, ensure_ascii=False),
             zone, ts, image, clip, round(confidence, 4)),
        )

    def list_violations(
        self,
        limit: int = 50,
        offset: int = 0,
        cam_id: str | None = None,
        since: float | None = None,
        unack_only: bool = False,
    ) -> list[dict]:
        sql = "SELECT * FROM violations WHERE 1=1"
        args: list[Any] = []
        if cam_id:
            sql += " AND cam_id = ?"
            args.append(cam_id)
        if since:
            sql += " AND ts >= ?"
            args.append(since)
        if unack_only:
            sql += " AND acknowledged = 0"
        sql += " ORDER BY ts DESC LIMIT ? OFFSET ?"
        args += [limit, offset]
        rows = self._rows(sql, args)
        for r in rows:
            r["missing"] = json.loads(r["missing"])
            r["acknowledged"] = bool(r["acknowledged"])
        return rows

    def acknowledge(self, violation_id: int, by: str = "operator") -> None:
        self._write(
            "UPDATE violations SET acknowledged = 1, ack_by = ?, ack_at = ? WHERE id = ?",
            (by, time.time(), violation_id),
        )

    def violation_counts(self, since: float) -> list[dict]:
        return self._rows(
            """SELECT cam_id, zone, missing, COUNT(*) AS n
               FROM violations WHERE ts >= ?
               GROUP BY cam_id, zone, missing""",
            (since,),
        )

    def summary(self, since: float) -> dict:
        row = self._rows(
            """SELECT COUNT(*) AS total,
                      SUM(CASE WHEN acknowledged = 0 THEN 1 ELSE 0 END) AS unack,
                      COUNT(DISTINCT cam_id) AS cameras,
                      COUNT(DISTINCT track_id) AS tracks
               FROM violations WHERE ts >= ?""",
            (since,),
        )[0]
        return {k: (v or 0) for k, v in row.items()}

    def hourly_series(self, since: float) -> list[dict]:
        return self._rows(
            """SELECT CAST((ts - ?) / 3600 AS INTEGER) AS bucket, COUNT(*) AS n
               FROM violations WHERE ts >= ?
               GROUP BY bucket ORDER BY bucket""",
            (since, since),
        )

    # ---------------- events ----------------
    def log_event(self, level: str, cam_id: str | None, message: str) -> None:
        self._write(
            "INSERT INTO events (ts, level, cam_id, message) VALUES (?, ?, ?, ?)",
            (time.time(), level, cam_id, message),
        )

    def list_events(self, limit: int = 100) -> list[dict]:
        return self._rows("SELECT * FROM events ORDER BY ts DESC LIMIT ?", (limit,))

    # ---------------- camera status ----------------
    def update_status(
        self,
        cam_id: str,
        online: bool,
        fps: float,
        latency_ms: float,
        persons: int,
        last_error: str | None = None,
    ) -> None:
        self._write(
            """INSERT INTO camera_status
               (cam_id, online, fps, latency_ms, persons, last_frame, last_error)
               VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(cam_id) DO UPDATE SET
                 online=excluded.online, fps=excluded.fps,
                 latency_ms=excluded.latency_ms, persons=excluded.persons,
                 last_frame=excluded.last_frame, last_error=excluded.last_error""",
            (cam_id, 1 if online else 0, round(fps, 2), round(latency_ms, 1),
             persons, time.time(), last_error),
        )

    def camera_status(self) -> list[dict]:
        rows = self._rows("SELECT * FROM camera_status ORDER BY cam_id")
        for r in rows:
            r["online"] = bool(r["online"])
        return rows

    # ---------------- don dep ----------------
    def prune_violations(
        self,
        before: float | None = None,
        unack_before: float | None = None,
        ack_before: float | None = None,
    ) -> int:
        """Xoa vi pham qua han. Tra ve so ban ghi da xoa."""
        deleted = 0
        if before is not None:
            with self._lock:
                con = self._conn()
                try:
                    cur = con.execute("DELETE FROM violations WHERE ts < ?", (before,))
                    con.commit()
                    deleted = cur.rowcount or 0
                finally:
                    con.close()
            return deleted

        with self._lock:
            con = self._conn()
            try:
                if unack_before is not None:
                    cur = con.execute(
                        "DELETE FROM violations WHERE acknowledged = 0 AND ts < ?",
                        (unack_before,),
                    )
                    deleted += cur.rowcount or 0
                if ack_before is not None:
                    cur = con.execute(
                        "DELETE FROM violations WHERE acknowledged = 1 AND ts < ?",
                        (ack_before,),
                    )
                    deleted += cur.rowcount or 0
                con.commit()
            finally:
                con.close()
        return deleted

    def prune_events(self, before: float) -> int:
        with self._lock:
            con = self._conn()
            try:
                cur = con.execute("DELETE FROM events WHERE ts < ?", (before,))
                con.commit()
                return cur.rowcount or 0
            finally:
                con.close()

    def vacuum(self) -> None:
        with self._lock:
            con = self._conn()
            try:
                con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                con.execute("VACUUM")
            finally:
                con.close()

    def db_size(self) -> int:
        try:
            return Path(self.path).stat().st_size
        except OSError:
            return 0

    def count_violations(self) -> int:
        row = self._rows("SELECT COUNT(*) AS n FROM violations")[0]
        return int(row["n"] or 0)
