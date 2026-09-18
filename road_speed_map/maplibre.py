from __future__ import annotations

import gzip
import json
from typing import Any

from road_speed_map.overrides import OverrideStore
from road_speed_map.speeds import OBSERVED_FEATURE_SPEEDS, speed_color


def _hex_color(rgb: list[int]) -> str:
    return f"#{rgb[0]:02x}{rgb[1]:02x}{rgb[2]:02x}"


def encode_map_payload(
    rows: list[dict[str, Any]],
    *,
    center: tuple[float, float],
    zoom: float,
    overrides: dict[str, dict[str, Any]],
    observations: dict[str, dict[str, Any]],
) -> bytes:
    """MapLibreコンポーネントへ渡すGeoJSONをgzip圧縮する。"""
    features: list[dict[str, Any]] = []
    for row in rows:
        segment_id = str(row["segment_id"])
        color = speed_color(row.get("speed_kmh"))
        basis = str(row.get("basis") or "unknown")
        if basis == "statutory_inference":
            width, opacity = 3, 0.6
        elif basis == "human_observation":
            width, opacity = 4, 0.82
        else:
            width = 7 if (row.get("speed_kmh") or 0) >= 70 else 5
            opacity = 0.9 if basis == "unknown" else 1.0

        override = overrides.get(segment_id) or {}
        observation = observations.get(segment_id) or {}
        features.append(
            {
                "type": "Feature",
                "id": segment_id,
                "geometry": {"type": "LineString", "coordinates": row["path"]},
                "properties": {
                    "id": segment_id,
                    "road": row.get("road_label") or "名称なし",
                    "speed": row.get("speed_kmh"),
                    "speed_label": row.get("speed_label") or "不明",
                    "basis": basis,
                    "basis_label": row.get("basis_label") or "判定材料不足",
                    "confidence": row.get("confidence_label") or "不明",
                    "reason": row.get("reason") or "",
                    "color": _hex_color(color),
                    "width": width,
                    "opacity": opacity,
                    "override_speed": override.get("speed_kmh"),
                    "override_evidence": override.get("evidence_type") or "",
                    "override_url": override.get("evidence_url") or "",
                    "override_note": override.get("note") or "",
                    "observation_feature": observation.get("observed_feature") or "",
                    "observation_sign": observation.get("sign_status") or "",
                    "observation_evidence": observation.get("evidence_type") or "",
                    "observation_url": observation.get("evidence_url") or "",
                    "observation_note": observation.get("note") or "",
                },
            }
        )

    latitude, longitude = center
    payload = {
        "center": [longitude, latitude],
        "zoom": zoom,
        "geojson": {"type": "FeatureCollection", "features": features},
    }
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return gzip.compress(encoded, compresslevel=6)


def apply_map_edit(
    store: OverrideStore,
    rows: list[dict[str, Any]],
    target_ids: list[str],
    payload: dict[str, Any],
) -> tuple[int, str]:
    """MapLibreポップアップから届いた保存・削除操作を補正DBへ反映する。"""
    action = str(payload.get("action") or "")
    target_set = {str(segment_id) for segment_id in target_ids}
    targets = [row for row in rows if str(row.get("segment_id")) in target_set]
    if not targets:
        return 0, "対象道路が見つかりませんでした。"

    if action == "delete_speed":
        for target in targets:
            store.delete(str(target["segment_id"]))
        return len(targets), f"速度標識の補正を {len(targets):,} セグメントから削除しました。"
    if action == "delete_observation":
        for target in targets:
            store.delete_observation(str(target["segment_id"]))
        return len(targets), f"道路構造の観測を {len(targets):,} セグメントから削除しました。"

    common = {
        "evidence_url": str(payload.get("evidence_url") or "").strip(),
        "note": str(payload.get("note") or "").strip(),
    }
    if action == "save_speed":
        try:
            speed = int(payload["speed_kmh"])
        except (KeyError, TypeError, ValueError):
            return 0, "最高速度を数値で入力してください。"
        if not 5 <= speed <= 130:
            return 0, "最高速度は5～130 km/hで入力してください。"
        for target in targets:
            store.upsert(
                **_target_metadata(target),
                speed_kmh=speed,
                evidence_type=str(payload.get("evidence_type") or "その他"),
                **common,
            )
        return len(targets), f"速度標識の補正を {len(targets):,} セグメントへ保存しました。"

    if action == "save_observation":
        feature = str(payload.get("observed_feature") or "")
        if feature not in OBSERVED_FEATURE_SPEEDS:
            return 0, "確認した道路構造を選択してください。"
        sign_status = str(payload.get("sign_status") or "not_checked")
        if sign_status not in {"not_checked", "none_in_selected_range"}:
            return 0, "速度標識の確認状況が不正です。"
        for target in targets:
            store.upsert_observation(
                **_target_metadata(target),
                observed_feature=feature,
                sign_status=sign_status,
                evidence_type=str(payload.get("evidence_type") or "その他"),
                **common,
            )
        return len(targets), f"道路構造の観測を {len(targets):,} セグメントへ保存しました。"

    return 0, "未対応の操作です。"


def _target_metadata(target: dict[str, Any]) -> dict[str, Any]:
    path = target.get("path") or []
    return {
        "segment_id": str(target["segment_id"]),
        "osm_way_id": int(target["osm_way_id"]),
        "from_node": str(target["from_node"]),
        "to_node": str(target["to_node"]),
        "road_name": str(target.get("road_name") or ""),
        "midpoint_lat": sum(point[1] for point in path) / len(path) if path else None,
        "midpoint_lon": sum(point[0] for point in path) / len(path) if path else None,
    }
