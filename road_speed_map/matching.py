from __future__ import annotations

import math
from typing import Any

from shapely.geometry import LineString, Point, Polygon
from shapely.strtree import STRtree


def _project_path(path: list[list[float]], latitude: float) -> list[tuple[float, float]]:
    meters_per_degree_lon = 111_320.0 * math.cos(math.radians(latitude))
    meters_per_degree_lat = 110_540.0
    return [
        (float(longitude) * meters_per_degree_lon, float(point_lat) * meters_per_degree_lat)
        for longitude, point_lat in path
    ]


def _line_angle(line: LineString, point: Point) -> float | None:
    if line.length <= 0:
        return None
    position = line.project(point)
    span = min(8.0, line.length / 2)
    before = line.interpolate(max(0.0, position - span))
    after = line.interpolate(min(line.length, position + span))
    if before.equals(after):
        return None
    return math.degrees(math.atan2(after.y - before.y, after.x - before.x)) % 180


def _angle_difference(first: float, second: float) -> float:
    return abs((first - second + 90) % 180 - 90)


def match_jartic_to_segments(
    segments: list[dict[str, Any]],
    jartic_lines: list[dict[str, Any]],
    jartic_areas: list[dict[str, Any]],
    bbox: tuple[float, float, float, float],
    *,
    max_distance_m: float = 15.0,
    max_angle_degrees: float = 25.0,
) -> dict[str, dict[str, Any]]:
    """JARTICの原典形状を、近接距離と進行方向でOSMセグメントへ対応付ける。"""
    latitude = (bbox[0] + bbox[2]) / 2

    line_features: list[dict[str, Any]] = []
    line_geometries: list[LineString] = []
    for feature in jartic_lines:
        try:
            geometry = LineString(_project_path(feature["path"], latitude))
        except (KeyError, TypeError, ValueError):
            continue
        if geometry.length > 0:
            line_features.append(feature)
            line_geometries.append(geometry)
    line_tree = STRtree(line_geometries) if line_geometries else None

    area_features: list[dict[str, Any]] = []
    area_geometries: list[Polygon] = []
    for feature in jartic_areas:
        try:
            geometry = Polygon(_project_path(feature["path"], latitude))
        except (KeyError, TypeError, ValueError):
            continue
        if geometry.is_valid and not geometry.is_empty:
            area_features.append(feature)
            area_geometries.append(geometry)
    area_tree = STRtree(area_geometries) if area_geometries else None

    matches: dict[str, dict[str, Any]] = {}
    for segment in segments:
        try:
            road = LineString(_project_path(segment["path"], latitude))
        except (KeyError, TypeError, ValueError):
            continue
        if road.length <= 0:
            continue
        midpoint = road.interpolate(0.5, normalized=True)

        if area_tree is not None:
            containing = [
                int(index)
                for index in area_tree.query(midpoint)
                if midpoint.within(area_geometries[int(index)])
            ]
            if containing:
                feature = area_features[containing[0]]
                matches[str(segment["segment_id"])] = {
                    **feature,
                    "distance_m": 0.0,
                    "match_kind": "area",
                }
                continue

        if line_tree is None:
            continue
        road_angle = _line_angle(road, midpoint)
        if road_angle is None:
            continue

        best: tuple[float, int] | None = None
        for raw_index in line_tree.query(midpoint, predicate="dwithin", distance=max_distance_m):
            index = int(raw_index)
            official = line_geometries[index]
            official_angle = _line_angle(official, midpoint)
            if official_angle is None:
                continue
            if _angle_difference(road_angle, official_angle) > max_angle_degrees:
                continue
            distance = midpoint.distance(official)
            if best is None or distance < best[0]:
                best = (distance, index)

        if best is not None:
            distance, index = best
            matches[str(segment["segment_id"])] = {
                **line_features[index],
                "distance_m": distance,
                "match_kind": "line",
            }
    return matches
