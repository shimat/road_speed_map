from __future__ import annotations

import csv
import json
import os
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from typing import Any

JARTIC_BASE = "https://www.jartic.or.jp/d/opendata"
JARTIC_MANIFEST = f"{JARTIC_BASE}/opendata.json"
SPEED_REGULATION_CODES = {"112", "113", "114"}


class JarticError(RuntimeError):
    pass


def _download(url: str, timeout: int = 120) -> bytes:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "road-speed-map-poc/0.1 (local Streamlit application)"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read()
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise JarticError(f"JARTICデータを取得できませんでした: {exc}") from exc


def fetch_jartic_snapshot(cache_dir: Path, *, refresh: bool = False) -> tuple[Path, dict[str, str]]:
    cache_dir.mkdir(parents=True, exist_ok=True)
    pointer = cache_dir / "current.json"
    if pointer.exists() and not refresh:
        metadata = json.loads(pointer.read_text(encoding="utf-8"))
        archive = cache_dir / metadata["archive_name"]
        if archive.exists():
            return archive, metadata

    manifest = json.loads(_download(JARTIC_MANIFEST, timeout=30))
    type_d = next((entry for entry in manifest if entry.get("type") == "typeD"), None)
    if not type_d:
        raise JarticError("JARTIC公開一覧に交通規制情報がありません。")
    hokkaido = next(
        (entry for entry in type_d.get("targetList", []) if entry.get("id") == "R01"), None
    )
    if not hokkaido:
        raise JarticError("JARTIC公開一覧に北海道の交通規制情報がありません。")

    relative_link = str(hokkaido["link"])
    url = f"{JARTIC_BASE}{relative_link}"
    link_parts = relative_link.strip("/").split("/")
    archive_name = f"{link_parts[-2]}-{link_parts[-1]}" if len(link_parts) >= 2 else link_parts[-1]
    archive = cache_dir / archive_name
    if not archive.exists() or refresh:
        payload = _download(url)
        temporary = archive.with_suffix(".tmp")
        temporary.write_bytes(payload)
        try:
            with zipfile.ZipFile(temporary) as zipped:
                if not any(name.lower().endswith(".csv") for name in zipped.namelist()):
                    raise JarticError("JARTIC ZIPにCSVが含まれていません。")
        except zipfile.BadZipFile as exc:
            temporary.unlink(missing_ok=True)
            raise JarticError("JARTICから不正なZIPを受信しました。") from exc
        os.replace(temporary, archive)

    metadata = {
        "archive_name": archive_name,
        "target_month": str(type_d.get("targetMonth", "")),
        "release_day": str(type_d.get("releaseDay", "")),
        "source_url": url,
    }
    temporary_pointer = pointer.with_suffix(".tmp")
    temporary_pointer.write_text(json.dumps(metadata, ensure_ascii=False), encoding="utf-8")
    os.replace(temporary_pointer, pointer)
    return archive, metadata


def parse_coordinate_parts(value: str) -> list[list[list[float]]]:
    parts: list[list[list[float]]] = []
    for raw_part in value.split("/"):
        points: list[list[float]] = []
        for raw_point in raw_part.split(";"):
            values = raw_point.strip().split()
            if len(values) != 2:
                continue
            try:
                lon, lat = map(float, values)
            except ValueError:
                continue
            if -180 <= lon <= 180 and -90 <= lat <= 90:
                points.append([lon, lat])
        if len(points) >= 2:
            parts.append(points)
    return parts


def intersects_bbox(path: list[list[float]], bbox: tuple[float, float, float, float]) -> bool:
    south, west, north, east = bbox
    longitudes = [point[0] for point in path]
    latitudes = [point[1] for point in path]
    return not (
        max(longitudes) < west
        or min(longitudes) > east
        or max(latitudes) < south
        or min(latitudes) > north
    )


def load_jartic_speed_features(
    archive: Path, bbox: tuple[float, float, float, float]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    lines: list[dict[str, Any]] = []
    areas: list[dict[str, Any]] = []
    with zipfile.ZipFile(archive) as zipped:
        csv_name = next(name for name in zipped.namelist() if name.lower().endswith(".csv"))
        with zipped.open(csv_name) as binary:
            reader = csv.DictReader(
                (line.decode("cp932") for line in binary),
                skipinitialspace=False,
            )
            for record in reader:
                regulation_code = record.get("共通規制種別コード", "")
                if regulation_code not in SPEED_REGULATION_CODES:
                    continue
                try:
                    speed = int(record.get("速度", ""))
                except ValueError:
                    continue
                coordinate_parts = parse_coordinate_parts(record.get("規制場所の経度緯度", ""))
                for part_index, path in enumerate(coordinate_parts):
                    if not intersects_bbox(path, bbox):
                        continue
                    unique_key = record.get("ユニークキー", "unknown")
                    regulation_name = record.get("県別規制種別名称") or "指定速度"
                    condition = record.get("規制条件", "").strip()
                    content = record.get("規制内容", "").strip()
                    feature = {
                        "jartic_id": f"jartic:{unique_key}:{part_index}",
                        "path": path,
                        "speed_kmh": speed,
                        "speed_label": f"{speed} km/h",
                        "road_label": f"JARTIC: {regulation_name}",
                        "basis": "jartic_source",
                        "basis_label": "JARTIC交通規制情報",
                        "confidence_label": "高（原典表示・現地標識優先）",
                        "reason": condition or content or "JARTIC公開座標の原典表示",
                        "regulation_code": regulation_code,
                        "regulation_name": regulation_name,
                        "condition": condition,
                        "content": content,
                        "decision_date": record.get("意思決定日(新規)", "").strip(),
                        "revision_date": record.get("意思決定改正日", "").strip(),
                        "updated_date": record.get("データ更新日", "").strip(),
                        "side_code": record.get("片側・両側コード", "").strip(),
                        "direction_code": record.get("方位コード", "").strip(),
                    }
                    if regulation_code == "114" and len(path) >= 3:
                        areas.append(feature)
                    else:
                        lines.append(feature)
    return lines, areas
