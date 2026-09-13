from __future__ import annotations

import re
from typing import Any

from road_speed_map.config import SPEED_COLORS

NUMERIC_SPEED = re.compile(r"^\s*(\d{1,3})(?:\s*km/?h)?\s*$", re.IGNORECASE)

BASIS_LABELS = {
    "manual": "手動確認",
    "jartic": "JARTIC指定速度（自動対応）",
    "osm": "OSMのmaxspeed",
    "human_observation": "人間が確認した道路構造から法定速度候補",
    "statutory_inference": "道路構造から法定速度を推定",
    "unknown": "判定材料不足",
}

CONFIDENCE_LABELS = {
    "high": "高",
    "medium": "中",
    "low": "低",
    "unknown": "不明",
}

OBSERVED_FEATURE_SPEEDS = {
    "center_line": 60,
    "traffic_lanes": 60,
    "direction_separation": 60,
    "no_center_line": 30,
}

OBSERVED_FEATURE_LABELS = {
    "center_line": "中央線を確認",
    "traffic_lanes": "車両通行帯を確認",
    "direction_separation": "中央分離帯・上下線分離を確認",
    "no_center_line": "中央線・車両通行帯・上下線分離がないことを確認",
}


def parse_speed(value: Any) -> int | None:
    if value is None:
        return None
    match = NUMERIC_SPEED.fullmatch(str(value))
    if not match:
        return None
    speed = int(match.group(1))
    return speed if 5 <= speed <= 130 else None


def parse_lanes(value: Any) -> int | None:
    if value is None:
        return None
    try:
        lanes = int(str(value).strip())
    except ValueError:
        return None
    return lanes if 1 <= lanes <= 20 else None


def osm_explicit_speed(tags: dict[str, Any]) -> tuple[int | None, str | None]:
    speed = parse_speed(tags.get("maxspeed"))
    if speed is not None:
        return speed, None

    forward = parse_speed(tags.get("maxspeed:forward"))
    backward = parse_speed(tags.get("maxspeed:backward"))
    oneway = str(tags.get("oneway", "")).lower() in {"yes", "1", "true", "-1"}
    if oneway:
        selected = backward if str(tags.get("oneway")) == "-1" else forward
        if selected is not None:
            return selected, None
    if forward is not None and forward == backward:
        return forward, None
    if forward is not None or backward is not None:
        return None, "方向別の速度を単一線で表現できません"
    return None, None


def infer_statutory_speed(tags: dict[str, Any]) -> tuple[int | None, str, str]:
    highway = str(tags.get("highway", ""))
    if highway in {"motorway", "motorway_link"}:
        return None, "高速道路は車種等で法定速度が異なります", "unknown"

    lane_markings = str(tags.get("lane_markings", "")).lower()
    divider = str(tags.get("divider", "")).lower()
    lanes = parse_lanes(tags.get("lanes"))
    oneway = str(tags.get("oneway", "")).lower() in {"yes", "1", "true", "-1"}

    if str(tags.get("motorroad", "")).lower() == "yes":
        return 60, "自動車専用道路タグあり", "medium"
    if divider and divider not in {"no", "none", "false", "0"}:
        return 60, "往復方向を分離する構造タグあり", "medium"
    if lane_markings == "yes" and lanes and lanes >= 2:
        return 60, "車線標示と複数車線のタグあり", "medium"
    if not oneway and lanes and lanes >= 2 and lane_markings != "no":
        return 60, "複数車線から中央線ありと推定", "low"
    if lane_markings == "no":
        return 30, "車線標示なしタグあり", "medium"
    if not oneway and lanes == 1:
        return 30, "1車線タグから中央線等なしと推定", "low"
    if highway in {"residential", "service", "living_street", "unclassified"}:
        return 30, "生活道路系の道路種別から推定（中央線等は未確認）", "low"
    return None, "中央線・車両通行帯を判断できません", "unknown"


def speed_color(speed: int | None) -> list[int]:
    if speed is None:
        return SPEED_COLORS["unknown"]
    if speed in SPEED_COLORS:
        return SPEED_COLORS[speed]
    known = sorted(key for key in SPEED_COLORS if isinstance(key, int))
    nearest = min(known, key=lambda candidate: abs(candidate - speed))
    return SPEED_COLORS[nearest]


def enrich_segment(
    segment: dict[str, Any],
    override: dict[str, Any] | None = None,
    jartic_match: dict[str, Any] | None = None,
    *,
    infer_statutory: bool = True,
) -> dict[str, Any]:
    row = {**segment}
    reason: str
    if override:
        speed = int(override["speed_kmh"])
        basis = "manual"
        confidence = "high"
        reason = override.get("evidence_type") or "手動確認"
    elif jartic_match:
        speed = int(jartic_match["speed_kmh"])
        basis = "jartic"
        confidence = "medium"
        distance = float(jartic_match.get("distance_m", 0.0))
        reason = f"JARTIC指定区間と位置・方向が一致（距離 {distance:.1f} m）"
    else:
        speed, problem = osm_explicit_speed(segment["tags"])
        if speed is not None:
            basis = "osm"
            confidence = "medium"
            reason = "OSMに数値のmaxspeedあり"
        elif problem:
            basis = "unknown"
            confidence = "unknown"
            reason = problem
        elif not infer_statutory:
            speed = None
            basis = "unknown"
            confidence = "unknown"
            reason = "JARTIC指定速度・OSMの数値maxspeedなし"
        else:
            speed, reason, confidence = infer_statutory_speed(segment["tags"])
            basis = "statutory_inference" if speed is not None else "unknown"

    row.update(
        {
            "speed_kmh": speed,
            "speed_label": f"{speed} km/h" if speed is not None else "不明",
            "basis": basis,
            "basis_label": BASIS_LABELS[basis],
            "confidence": confidence,
            "confidence_label": CONFIDENCE_LABELS[confidence],
            "reason": reason,
            "color": speed_color(speed),
        }
    )
    return row


def enrich_segments(
    segments: list[dict[str, Any]],
    overrides: dict[str, dict[str, Any]],
    jartic_matches: dict[str, dict[str, Any]] | None = None,
    *,
    infer_statutory: bool = True,
) -> list[dict[str, Any]]:
    matches = jartic_matches or {}
    return [
        enrich_segment(
            segment,
            overrides.get(segment["segment_id"]),
            matches.get(segment["segment_id"]),
            infer_statutory=infer_statutory,
        )
        for segment in segments
    ]


def source_data_only(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """原典の速度値だけを残し、手動補正と道路構造推定を取り除く。"""
    return [
        row if row.get("basis") in {"jartic", "osm"} else enrich_segment(row, infer_statutory=False)
        for row in rows
    ]


def apply_structure_observation(row: dict[str, Any], observation: dict[str, Any]) -> dict[str, Any]:
    """人間が確認した道路構造から法定速度候補を作る。指定速度値は上書きしない。"""
    feature = str(observation.get("observed_feature", ""))
    speed = OBSERVED_FEATURE_SPEEDS.get(feature)
    if speed is None:
        return row

    sign_status = str(observation.get("sign_status", "not_checked"))
    sign_note = (
        "選択区間内に指定速度標識なしを確認"
        if sign_status == "none_in_selected_range"
        else "指定速度標識は未確認"
    )
    result = {**row}
    result.update(
        {
            "speed_kmh": speed,
            "speed_label": f"{speed} km/h候補",
            "basis": "human_observation",
            "basis_label": BASIS_LABELS["human_observation"],
            "confidence": "medium",
            "confidence_label": CONFIDENCE_LABELS["medium"],
            "reason": f"{OBSERVED_FEATURE_LABELS[feature]}・{sign_note}",
            "color": speed_color(speed),
        }
    )
    return result


def apply_human_knowledge(
    rows: list[dict[str, Any]],
    overrides: dict[str, dict[str, Any]],
    observations: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """標識確認を最優先し、指定速度のない道路にだけ構造観測を適用する。"""
    result: list[dict[str, Any]] = []
    for row in rows:
        segment_id = row["segment_id"]
        if override := overrides.get(segment_id):
            result.append(enrich_segment(row, override))
        elif observation := observations.get(segment_id):
            if row.get("basis") in {"jartic", "osm"}:
                result.append(row)
            else:
                result.append(apply_structure_observation(row, observation))
        else:
            result.append(row)
    return result


def apply_manual_overrides(
    rows: list[dict[str, Any]], overrides: dict[str, dict[str, Any]]
) -> list[dict[str, Any]]:
    """事前判定済みデータへ手動補正だけを重ねる。"""
    return [
        enrich_segment(row, override) if (override := overrides.get(row["segment_id"])) else row
        for row in rows
    ]
