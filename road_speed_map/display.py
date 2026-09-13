from __future__ import annotations

from typing import Any

from shapely.geometry import LineString


def merge_contiguous_segments(
    rows: list[dict[str, Any]], *, simplify_tolerance: float = 0.0
) -> list[dict[str, Any]]:
    """同じOSM way上で速度判定が同じ連続エッジを表示用の1本の線へまとめる。"""
    merged: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    current_key: tuple[Any, ...] | None = None

    for row in rows:
        manual_identity = row["segment_id"] if row.get("basis") == "manual" else None
        key = (
            row.get("osm_way_id"),
            row.get("basis"),
            row.get("speed_kmh"),
            row.get("road_label"),
            manual_identity,
        )
        can_extend = (
            current is not None
            and key == current_key
            and current.get("to_node") == row.get("from_node")
            and current["path"][-1] == row["path"][0]
        )
        if can_extend:
            current["path"].append(row["path"][-1])
            current["segment_ids"].append(row["segment_id"])
            current["to_node"] = row.get("to_node")
            continue

        current = {
            **row,
            "path": [*row["path"]],
            "segment_ids": [row["segment_id"]],
        }
        merged.append(current)
        current_key = key

    if simplify_tolerance > 0:
        for row in merged:
            if len(row["path"]) <= 2:
                continue
            simplified = LineString(row["path"]).simplify(
                simplify_tolerance, preserve_topology=False
            )
            row["path"] = [[float(lon), float(lat)] for lon, lat in simplified.coords]
    return merged
