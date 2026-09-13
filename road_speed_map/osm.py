from __future__ import annotations

import hashlib
import json
import math
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any

OVERPASS_ENDPOINT = "https://overpass-api.de/api/interpreter"
EXCLUDED_HIGHWAYS = (
    "footway|path|cycleway|steps|pedestrian|bridleway|corridor|construction|proposed|raceway"
)


class OverpassError(RuntimeError):
    pass


def build_query(bbox: tuple[float, float, float, float]) -> str:
    south, west, north, east = bbox
    return f"""
[out:json][timeout:120];
way
  ["highway"]
  ["highway"!~"{EXCLUDED_HIGHWAYS}"]
  ["area"!="yes"]
  ({south},{west},{north},{east});
out tags geom;
""".strip()


def bbox_tiles(
    bbox: tuple[float, float, float, float], max_span: float = 0.05
) -> list[tuple[float, float, float, float]]:
    south, west, north, east = bbox
    latitude_parts = max(1, math.ceil((north - south) / max_span))
    longitude_parts = max(1, math.ceil((east - west) / max_span))
    latitude_step = (north - south) / latitude_parts
    longitude_step = (east - west) / longitude_parts
    return [
        (
            south + latitude_index * latitude_step,
            west + longitude_index * longitude_step,
            south + (latitude_index + 1) * latitude_step,
            west + (longitude_index + 1) * longitude_step,
        )
        for latitude_index in range(latitude_parts)
        for longitude_index in range(longitude_parts)
    ]


def snapshot_path(bbox: tuple[float, float, float, float], cache_dir: Path) -> Path:
    identity = ",".join(f"{value:.6f}" for value in bbox)
    digest = hashlib.sha256(identity.encode()).hexdigest()[:12]
    return cache_dir / f"osm-{digest}.json"


def _fetch_tile(
    tile: tuple[float, float, float, float],
    cache_dir: Path,
    *,
    refresh: bool,
) -> dict[str, Any]:
    tile_dir = cache_dir / "tiles"
    tile_path = snapshot_path(tile, tile_dir)
    if tile_path.exists() and not refresh:
        return json.loads(tile_path.read_text(encoding="utf-8"))

    query = build_query(tile)
    body = urllib.parse.urlencode({"data": query}).encode("utf-8")
    request = urllib.request.Request(
        OVERPASS_ENDPOINT,
        data=body,
        headers={
            "User-Agent": "road-speed-map-poc/0.1 (local Streamlit application)",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        },
        method="POST",
    )
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=150) as response:
                parsed = json.loads(response.read())
            if not isinstance(parsed.get("elements"), list):
                raise OverpassError("Overpass API応答に道路データがありません。")
            tile_dir.mkdir(parents=True, exist_ok=True)
            temporary = tile_path.with_suffix(".tmp")
            temporary.write_text(
                json.dumps(parsed, ensure_ascii=False, separators=(",", ":")), encoding="utf-8"
            )
            os.replace(temporary, tile_path)
            return parsed
        except urllib.error.HTTPError as exc:
            last_error = exc
            if exc.code not in {429, 502, 503, 504} or attempt == 2:
                break
            retry_after = exc.headers.get("Retry-After")
            try:
                delay = min(15, max(2, int(retry_after))) if retry_after else 5 * (attempt + 1)
            except ValueError:
                delay = 5 * (attempt + 1)
            time.sleep(delay)
        except (urllib.error.URLError, json.JSONDecodeError, TimeoutError, OSError) as exc:
            last_error = exc
            break
    raise OverpassError(str(last_error or "unknown error"))


def fetch_overpass_snapshot(
    bbox: tuple[float, float, float, float],
    cache_dir: Path,
    *,
    refresh: bool = False,
    progress_callback: Callable[[int, int], None] | None = None,
) -> Path:
    destination = snapshot_path(bbox, cache_dir)
    if destination.exists() and not refresh:
        return destination

    ways_by_id: dict[int, dict[str, Any]] = {}
    tiles = bbox_tiles(bbox)
    for tile_number, tile in enumerate(tiles, start=1):
        try:
            parsed = _fetch_tile(tile, cache_dir, refresh=refresh)
        except OverpassError as exc:
            if destination.exists():
                return destination
            raise OverpassError(
                f"OpenStreetMap道路データを取得できませんでした "
                f"（分割 {tile_number}/{len(tiles)}）: {exc}"
            ) from exc
        for element in parsed["elements"]:
            if element.get("type") == "way" and isinstance(element.get("id"), int):
                ways_by_id[element["id"]] = element
        if progress_callback:
            progress_callback(tile_number, len(tiles))

    combined = {
        "version": 0.6,
        "generator": "road-speed-map tiled Overpass fetch",
        "elements": list(ways_by_id.values()),
    }
    payload = json.dumps(combined, ensure_ascii=False, separators=(",", ":")).encode("utf-8")

    cache_dir.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(".tmp")
    temporary.write_bytes(payload)
    os.replace(temporary, destination)
    return destination


def load_segments(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return segments_from_overpass(data)


def segments_from_overpass(data: dict[str, Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for way in data.get("elements", []):
        if way.get("type") != "way":
            continue
        geometry = way.get("geometry") or []
        if len(geometry) < 2:
            continue
        nodes = way.get("nodes") or []
        tags = way.get("tags") or {}
        way_id = int(way["id"])
        road_name = tags.get("name") or tags.get("ref") or "名称なし"

        for index, (start, end) in enumerate(zip(geometry, geometry[1:], strict=False)):
            from_node = str(nodes[index]) if index < len(nodes) else f"g{index}"
            to_node = str(nodes[index + 1]) if index + 1 < len(nodes) else f"g{index + 1}"
            low_node, high_node = sorted((from_node, to_node))
            segment_id = f"osm:{way_id}:{low_node}:{high_node}"
            result.append(
                {
                    "segment_id": segment_id,
                    "osm_way_id": way_id,
                    "from_node": from_node,
                    "to_node": to_node,
                    "road_name": road_name,
                    "road_label": f"{road_name}（{tags.get('highway', '道路')}）",
                    "path": [
                        [float(start["lon"]), float(start["lat"])],
                        [float(end["lon"]), float(end["lat"])],
                    ],
                    "tags": tags,
                }
            )
    return result
