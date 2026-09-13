from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from road_speed_map.config import MAP_PRESETS
from road_speed_map.jartic import fetch_jartic_snapshot, load_jartic_speed_features
from road_speed_map.matching import match_jartic_to_segments
from road_speed_map.prepared import (
    extract_pbf_roads,
    load_prepared_segments,
    write_segments_parquet,
)
from road_speed_map.speeds import enrich_segments

PBF_URL = "https://download.geofabrik.de/asia/japan/hokkaido-latest.osm.pbf"
SOURCE_DIR = ROOT / "data" / "source"
PBF_PATH = SOURCE_DIR / "hokkaido-latest.osm.pbf"
PREPARED_REGIONS = {
    name: preset for name, preset in MAP_PRESETS.items() if preset.prepared_dataset is not None
}


def download_pbf(destination: Path, *, refresh: bool) -> bool:
    if destination.exists() and not refresh:
        print(f"PBFを再利用: {destination} ({destination.stat().st_size / 1_000_000:.1f} MB)")
        return False
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(".tmp")
    request = urllib.request.Request(
        PBF_URL,
        headers={"User-Agent": "road-speed-map-poc/0.1 (local preprocessing)"},
    )
    with urllib.request.urlopen(request, timeout=300) as response, temporary.open("wb") as output:
        total = int(response.headers.get("Content-Length", "0"))
        downloaded = 0
        while chunk := response.read(1024 * 1024):
            output.write(chunk)
            downloaded += len(chunk)
            if total:
                print(
                    f"\rPBFをダウンロード中: {downloaded / 1_000_000:.1f}/"
                    f"{total / 1_000_000:.1f} MB ({downloaded / total:.0%})",
                    end="",
                    flush=True,
                )
    print()
    os.replace(temporary, destination)
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description="北海道内の対象地域の道路データを事前生成します。")
    parser.add_argument(
        "--region",
        choices=["all", *PREPARED_REGIONS],
        default="all",
        help="生成する地域。省略時は全地域",
    )
    parser.add_argument("--refresh-pbf", action="store_true", help="北海道PBFを再取得する")
    parser.add_argument("--refresh-jartic", action="store_true", help="JARTIC原本を再取得する")
    parser.add_argument("--reextract", action="store_true", help="道路の抽出も強制的にやり直す")
    args = parser.parse_args()

    started = time.perf_counter()
    pbf_updated = download_pbf(PBF_PATH, refresh=args.refresh_pbf)
    archive, jartic_metadata = fetch_jartic_snapshot(
        ROOT / "data" / "cache" / "jartic", refresh=args.refresh_jartic
    )
    selected_regions = (
        PREPARED_REGIONS.items()
        if args.region == "all"
        else [(args.region, PREPARED_REGIONS[args.region])]
    )

    for region_name, preset in selected_regions:
        region_started = time.perf_counter()
        final_path = ROOT / str(preset.prepared_dataset)
        raw_path = final_path.with_name(f"{final_path.stem}-raw.parquet")
        metadata_path = final_path.with_suffix(".metadata.json")

        print(f"\n[{region_name}]")
        if raw_path.exists() and not pbf_updated and not args.reextract:
            print(f"抽出済み道路を再利用: {raw_path}")
            segments = load_prepared_segments(raw_path)
            raw_count = len(segments)
        else:
            print("北海道PBFから対象範囲の道路を抽出中…")
            raw_count = extract_pbf_roads(
                PBF_PATH,
                raw_path,
                preset.bbox,
                progress_callback=lambda count: print(f"  {count:,} セグメント抽出"),
            )
            print(f"道路抽出完了: {raw_count:,} セグメント")
            segments = load_prepared_segments(raw_path)

        jartic_lines, jartic_areas = load_jartic_speed_features(archive, preset.bbox)
        print("JARTIC指定速度を道路へ対応付け中…")
        matches = match_jartic_to_segments(segments, jartic_lines, jartic_areas, preset.bbox)
        enriched = enrich_segments(segments, {}, matches)
        final_count = write_segments_parquet(enriched, final_path)

        metadata = {
            "generated_at": datetime.now(UTC).isoformat(),
            "region_name": region_name,
            "pbf_url": PBF_URL,
            "pbf_size": PBF_PATH.stat().st_size,
            "bbox": preset.bbox,
            "segment_count": final_count,
            "jartic_match_count": len(matches),
            "jartic_target_month": jartic_metadata.get("target_month", ""),
            "elapsed_seconds": round(time.perf_counter() - region_started, 1),
        }
        metadata_path.write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(
            f"完了: {final_path} / {final_count:,} セグメント / "
            f"JARTIC対応 {len(matches):,} / {metadata['elapsed_seconds']}秒"
        )

    print(f"全処理時間: {time.perf_counter() - started:.1f}秒")


if __name__ == "__main__":
    main()
