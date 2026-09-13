from __future__ import annotations

import json
import os
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

import osmium
import pyarrow as pa
import pyarrow.parquet as pq

from road_speed_map.osm import EXCLUDED_HIGHWAYS

TAG_KEYS = (
    "highway",
    "name",
    "ref",
    "maxspeed",
    "maxspeed:forward",
    "maxspeed:backward",
    "oneway",
    "lanes",
    "lane_markings",
    "divider",
    "motorroad",
    "area",
)
EXCLUDED_HIGHWAY_VALUES = frozenset(EXCLUDED_HIGHWAYS.split("|"))

PARQUET_SCHEMA = pa.schema(
    [
        ("segment_id", pa.string()),
        ("osm_way_id", pa.int64()),
        ("from_node", pa.string()),
        ("to_node", pa.string()),
        ("road_name", pa.string()),
        ("road_label", pa.string()),
        ("start_lon", pa.float64()),
        ("start_lat", pa.float64()),
        ("end_lon", pa.float64()),
        ("end_lat", pa.float64()),
        ("tags_json", pa.string()),
        ("speed_kmh", pa.int16()),
        ("speed_label", pa.string()),
        ("basis", pa.string()),
        ("basis_label", pa.string()),
        ("confidence", pa.string()),
        ("confidence_label", pa.string()),
        ("reason", pa.string()),
        ("color", pa.list_(pa.uint8())),
    ]
)


def _edge_intersects_bbox(
    start: tuple[float, float],
    end: tuple[float, float],
    bbox: tuple[float, float, float, float],
) -> bool:
    south, west, north, east = bbox
    return not (
        max(start[0], end[0]) < west
        or min(start[0], end[0]) > east
        or max(start[1], end[1]) < south
        or min(start[1], end[1]) > north
    )


def _parquet_row(row: dict[str, Any]) -> dict[str, Any]:
    path = row["path"]
    return {
        "segment_id": str(row["segment_id"]),
        "osm_way_id": int(row["osm_way_id"]),
        "from_node": str(row["from_node"]),
        "to_node": str(row["to_node"]),
        "road_name": str(row.get("road_name") or "名称なし"),
        "road_label": str(row.get("road_label") or "名称なし"),
        "start_lon": float(path[0][0]),
        "start_lat": float(path[0][1]),
        "end_lon": float(path[1][0]),
        "end_lat": float(path[1][1]),
        "tags_json": json.dumps(row.get("tags", {}), ensure_ascii=False, separators=(",", ":")),
        "speed_kmh": row.get("speed_kmh"),
        "speed_label": row.get("speed_label"),
        "basis": row.get("basis"),
        "basis_label": row.get("basis_label"),
        "confidence": row.get("confidence"),
        "confidence_label": row.get("confidence_label"),
        "reason": row.get("reason"),
        "color": row.get("color"),
    }


def write_segments_parquet(rows: Iterable[dict[str, Any]], destination: Path) -> int:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(".tmp.parquet")
    count = 0
    batch: list[dict[str, Any]] = []
    with pq.ParquetWriter(temporary, PARQUET_SCHEMA, compression="zstd") as writer:
        for row in rows:
            batch.append(_parquet_row(row))
            count += 1
            if len(batch) >= 50_000:
                writer.write_table(pa.Table.from_pylist(batch, schema=PARQUET_SCHEMA))
                batch.clear()
        if batch:
            writer.write_table(pa.Table.from_pylist(batch, schema=PARQUET_SCHEMA))
    os.replace(temporary, destination)
    return count


def extract_pbf_roads(
    source: Path,
    destination: Path,
    bbox: tuple[float, float, float, float],
    *,
    progress_callback: Callable[[int], None] | None = None,
) -> int:
    """北海道PBFを1回走査し、対象矩形と交差する自動車道路をParquetへ抽出する。"""

    def rows() -> Iterable[dict[str, Any]]:
        count = 0
        processor = (
            osmium.FileProcessor(source)
            .with_locations("flex_mem")
            .with_filter(osmium.filter.EntityFilter(osmium.osm.WAY))
            .with_filter(osmium.filter.KeyFilter("highway"))
        )
        for way in processor:
            highway = way.tags.get("highway", "")
            if highway in EXCLUDED_HIGHWAY_VALUES or way.tags.get("area", "") == "yes":
                continue
            tags = {key: value for key in TAG_KEYS if (value := way.tags.get(key)) is not None}
            nodes = [
                (str(node.ref), float(node.lon), float(node.lat))
                for node in way.nodes
                if node.location.valid()
            ]
            if len(nodes) < 2:
                continue
            road_name = tags.get("name") or tags.get("ref") or "名称なし"
            for start, end in zip(nodes, nodes[1:], strict=False):
                start_position = (start[1], start[2])
                end_position = (end[1], end[2])
                if not _edge_intersects_bbox(start_position, end_position, bbox):
                    continue
                low_node, high_node = sorted((start[0], end[0]))
                yield {
                    "segment_id": f"osm:{way.id}:{low_node}:{high_node}",
                    "osm_way_id": int(way.id),
                    "from_node": start[0],
                    "to_node": end[0],
                    "road_name": road_name,
                    "road_label": f"{road_name}（{highway}）",
                    "path": [[start[1], start[2]], [end[1], end[2]]],
                    "tags": tags,
                }
                count += 1
                if progress_callback and count % 25_000 == 0:
                    progress_callback(count)

    return write_segments_parquet(rows(), destination)


def load_prepared_segments(path: Path) -> list[dict[str, Any]]:
    columns = pq.read_table(path).to_pydict()
    result: list[dict[str, Any]] = []
    for index, segment_id in enumerate(columns["segment_id"]):
        row = {
            "segment_id": segment_id,
            "osm_way_id": columns["osm_way_id"][index],
            "from_node": columns["from_node"][index],
            "to_node": columns["to_node"][index],
            "road_name": columns["road_name"][index],
            "road_label": columns["road_label"][index],
            "path": [
                [columns["start_lon"][index], columns["start_lat"][index]],
                [columns["end_lon"][index], columns["end_lat"][index]],
            ],
            "tags": json.loads(columns["tags_json"][index]),
        }
        for key in (
            "speed_kmh",
            "speed_label",
            "basis",
            "basis_label",
            "confidence",
            "confidence_label",
            "reason",
            "color",
        ):
            value = columns[key][index]
            if value is not None:
                row[key] = value
        result.append(row)
    return result
