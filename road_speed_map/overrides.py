from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


class OverrideStore:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with closing(self._connect()) as connection, connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS speed_overrides (
                    segment_id TEXT PRIMARY KEY,
                    osm_way_id INTEGER NOT NULL,
                    from_node TEXT NOT NULL,
                    to_node TEXT NOT NULL,
                    road_name TEXT NOT NULL DEFAULT '',
                    speed_kmh INTEGER NOT NULL CHECK (speed_kmh BETWEEN 5 AND 130),
                    evidence_type TEXT NOT NULL,
                    evidence_url TEXT NOT NULL DEFAULT '',
                    note TEXT NOT NULL DEFAULT '',
                    midpoint_lat REAL,
                    midpoint_lon REAL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS road_observations (
                    segment_id TEXT PRIMARY KEY,
                    osm_way_id INTEGER NOT NULL,
                    from_node TEXT NOT NULL,
                    to_node TEXT NOT NULL,
                    road_name TEXT NOT NULL DEFAULT '',
                    observed_feature TEXT NOT NULL,
                    sign_status TEXT NOT NULL DEFAULT '未確認',
                    evidence_type TEXT NOT NULL,
                    evidence_url TEXT NOT NULL DEFAULT '',
                    note TEXT NOT NULL DEFAULT '',
                    midpoint_lat REAL,
                    midpoint_lon REAL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )

    def upsert(self, **values: Any) -> None:
        now = datetime.now(UTC).isoformat()
        with closing(self._connect()) as connection, connection:
            connection.execute(
                """
                INSERT INTO speed_overrides (
                    segment_id, osm_way_id, from_node, to_node, road_name, speed_kmh,
                    evidence_type, evidence_url, note, midpoint_lat, midpoint_lon,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(segment_id) DO UPDATE SET
                    osm_way_id=excluded.osm_way_id,
                    from_node=excluded.from_node,
                    to_node=excluded.to_node,
                    road_name=excluded.road_name,
                    speed_kmh=excluded.speed_kmh,
                    evidence_type=excluded.evidence_type,
                    evidence_url=excluded.evidence_url,
                    note=excluded.note,
                    midpoint_lat=excluded.midpoint_lat,
                    midpoint_lon=excluded.midpoint_lon,
                    updated_at=excluded.updated_at
                """,
                (
                    values["segment_id"],
                    values["osm_way_id"],
                    values["from_node"],
                    values["to_node"],
                    values.get("road_name", ""),
                    values["speed_kmh"],
                    values.get("evidence_type", "その他"),
                    values.get("evidence_url", ""),
                    values.get("note", ""),
                    values.get("midpoint_lat"),
                    values.get("midpoint_lon"),
                    now,
                    now,
                ),
            )

    def get(self, segment_id: str) -> dict[str, Any] | None:
        with closing(self._connect()) as connection, connection:
            row = connection.execute(
                "SELECT * FROM speed_overrides WHERE segment_id = ?", (segment_id,)
            ).fetchone()
        return dict(row) if row else None

    def delete(self, segment_id: str) -> None:
        with closing(self._connect()) as connection, connection:
            connection.execute("DELETE FROM speed_overrides WHERE segment_id = ?", (segment_id,))

    def list_all(self) -> list[dict[str, Any]]:
        with closing(self._connect()) as connection, connection:
            rows = connection.execute(
                "SELECT * FROM speed_overrides ORDER BY updated_at DESC"
            ).fetchall()
        return [dict(row) for row in rows]

    def as_mapping(self) -> dict[str, dict[str, Any]]:
        return {row["segment_id"]: row for row in self.list_all()}

    def upsert_observation(self, **values: Any) -> None:
        now = datetime.now(UTC).isoformat()
        with closing(self._connect()) as connection, connection:
            connection.execute(
                """
                INSERT INTO road_observations (
                    segment_id, osm_way_id, from_node, to_node, road_name,
                    observed_feature, sign_status, evidence_type, evidence_url,
                    note, midpoint_lat, midpoint_lon, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(segment_id) DO UPDATE SET
                    osm_way_id=excluded.osm_way_id,
                    from_node=excluded.from_node,
                    to_node=excluded.to_node,
                    road_name=excluded.road_name,
                    observed_feature=excluded.observed_feature,
                    sign_status=excluded.sign_status,
                    evidence_type=excluded.evidence_type,
                    evidence_url=excluded.evidence_url,
                    note=excluded.note,
                    midpoint_lat=excluded.midpoint_lat,
                    midpoint_lon=excluded.midpoint_lon,
                    updated_at=excluded.updated_at
                """,
                (
                    values["segment_id"],
                    values["osm_way_id"],
                    values["from_node"],
                    values["to_node"],
                    values.get("road_name", ""),
                    values["observed_feature"],
                    values.get("sign_status", "未確認"),
                    values.get("evidence_type", "その他"),
                    values.get("evidence_url", ""),
                    values.get("note", ""),
                    values.get("midpoint_lat"),
                    values.get("midpoint_lon"),
                    now,
                    now,
                ),
            )

    def get_observation(self, segment_id: str) -> dict[str, Any] | None:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT * FROM road_observations WHERE segment_id = ?", (segment_id,)
            ).fetchone()
        return dict(row) if row else None

    def delete_observation(self, segment_id: str) -> None:
        with closing(self._connect()) as connection, connection:
            connection.execute("DELETE FROM road_observations WHERE segment_id = ?", (segment_id,))

    def list_observations(self) -> list[dict[str, Any]]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                "SELECT * FROM road_observations ORDER BY updated_at DESC"
            ).fetchall()
        return [dict(row) for row in rows]

    def observations_mapping(self) -> dict[str, dict[str, Any]]:
        return {row["segment_id"]: row for row in self.list_observations()}
