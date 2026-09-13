from __future__ import annotations

import csv
import io
from pathlib import Path
from typing import Any

import pydeck as pdk
import streamlit as st

from road_speed_map.config import MAP_PRESETS, SPEED_COLORS, SPEED_LEGEND
from road_speed_map.display import merge_contiguous_segments
from road_speed_map.jartic import JarticError, fetch_jartic_snapshot, load_jartic_speed_features
from road_speed_map.matching import match_jartic_to_segments
from road_speed_map.osm import OverpassError, bbox_tiles, fetch_overpass_snapshot, load_segments
from road_speed_map.overrides import OverrideStore
from road_speed_map.prepared import load_prepared_segments
from road_speed_map.speeds import (
    apply_human_knowledge,
    enrich_segments,
    source_data_only,
    speed_color,
)

ROOT = Path(__file__).resolve().parent
CACHE_DIR = ROOT / "data" / "cache"
OVERRIDE_DB = ROOT / "data" / "overrides.sqlite3"
ROAD_LAYER_ID = "road-segments"
INFERRED_ROAD_LAYER_ID = "inferred-road-segments"
JARTIC_LINE_LAYER_ID = "jartic-speed-lines"
JARTIC_ZONE_LAYER_ID = "jartic-speed-zones"
MAP_ROW_FIELDS = {
    "segment_id",
    "path",
    "basis",
    "color",
}


st.set_page_config(page_title="道路最高速度マップ", page_icon="🛣️", layout="wide")


@st.cache_data(show_spinner=False)
def cached_load_segments(snapshot_path: str, modified_ns: int) -> list[dict[str, Any]]:
    del modified_ns  # ファイル更新時にキャッシュキーを変えるためだけに使用する。
    return load_segments(Path(snapshot_path))


@st.cache_resource(show_spinner=False)
def cached_load_prepared(dataset_path: str, modified_ns: int) -> list[dict[str, Any]]:
    del modified_ns
    return load_prepared_segments(Path(dataset_path))


@st.cache_data(show_spinner=False)
def cached_match_jartic(
    segments: list[dict[str, Any]],
    lines: list[dict[str, Any]],
    areas: list[dict[str, Any]],
    bbox: tuple[float, float, float, float],
) -> dict[str, dict[str, Any]]:
    return match_jartic_to_segments(segments, lines, areas, bbox)


def selected_object(event: Any) -> tuple[str | None, dict[str, Any] | None]:
    if event is None:
        return None, None
    selection = getattr(event, "selection", None)
    if selection is None and isinstance(event, dict):
        selection = event.get("selection")
    if not selection:
        return None, None
    objects = selection.get("objects", {})
    for layer_id in (
        JARTIC_LINE_LAYER_ID,
        JARTIC_ZONE_LAYER_ID,
        ROAD_LAYER_ID,
        INFERRED_ROAD_LAYER_ID,
    ):
        candidates = objects.get(layer_id, [])
        if candidates:
            return layer_id, candidates[0]
    return None, None


def render_deck(
    rows: list[dict[str, Any]],
    selected_id: str | None,
    jartic_lines: list[dict[str, Any]],
    jartic_areas: list[dict[str, Any]],
    view_center: tuple[float, float],
    view_zoom: float,
) -> pdk.Deck:
    for feature in [*jartic_lines, *jartic_areas]:
        color = SPEED_COLORS.get(feature["speed_kmh"], SPEED_COLORS["unknown"])
        feature["color"] = [*color[:3], 245]
        feature["fill_color"] = [*feature["color"][:3], 45]
        feature["line_width"] = 7 if feature["speed_kmh"] >= 70 else 5
        feature["tooltip_text"] = (
            f"{feature['road_label']}\n最高速度: {feature['speed_label']}\n"
            f"根拠: {feature['basis_label']}\n確度: {feature['confidence_label']}\n"
            f"{feature['reason']}"
        )

    zones = pdk.Layer(
        "PolygonLayer",
        jartic_areas,
        id=JARTIC_ZONE_LAYER_ID,
        get_polygon="path",
        get_fill_color="fill_color",
        get_line_color="color",
        get_line_width=3,
        line_width_min_pixels=2,
        stroked=True,
        filled=True,
        pickable=True,
        auto_highlight=True,
        highlight_color=[255, 255, 255, 120],
    )
    confirmed_rows = [row for row in rows if row["basis"] != "statutory_inference"]
    inferred_rows = [row for row in rows if row["basis"] == "statutory_inference"]
    roads = pdk.Layer(
        "PathLayer",
        confirmed_rows,
        id=ROAD_LAYER_ID,
        get_path="path",
        get_color="color",
        get_width="line_width",
        width_min_pixels=3,
        width_max_pixels=7,
        pickable=True,
        auto_highlight=True,
        highlight_color=[35, 35, 35, 190],
    )
    inferred_roads = pdk.Layer(
        "PathLayer",
        inferred_rows,
        id=INFERRED_ROAD_LAYER_ID,
        get_path="path",
        get_color="color",
        get_width="line_width",
        width_min_pixels=2,
        width_max_pixels=4,
        pickable=True,
        auto_highlight=True,
        highlight_color=[35, 35, 35, 190],
    )
    official_lines = pdk.Layer(
        "PathLayer",
        jartic_lines,
        id=JARTIC_LINE_LAYER_ID,
        get_path="path",
        get_color="color",
        get_width="line_width",
        width_min_pixels=4,
        width_max_pixels=9,
        pickable=True,
        auto_highlight=True,
        highlight_color=[255, 255, 255, 190],
    )
    manual_rows = [row for row in rows if row["basis"] == "manual"]
    manual_lines = pdk.Layer(
        "PathLayer",
        manual_rows,
        id="manual-speed-lines",
        get_path="path",
        get_color="color",
        get_width=6,
        width_min_pixels=5,
        width_max_pixels=10,
        pickable=False,
    )
    layers: list[pdk.Layer] = [zones, roads, inferred_roads, official_lines, manual_lines]
    if selected_id:
        selected_rows = [row for row in rows if row["segment_id"] == selected_id]
        if selected_rows:
            layers.extend(
                [
                    pdk.Layer(
                        "PathLayer",
                        selected_rows,
                        id="selected-road-halo",
                        get_path="path",
                        get_color=[25, 25, 25, 255],
                        get_width=10,
                        width_min_pixels=7,
                        pickable=False,
                    ),
                    pdk.Layer(
                        "PathLayer",
                        selected_rows,
                        id="selected-road",
                        get_path="path",
                        get_color="selection_color",
                        get_width=5,
                        width_min_pixels=4,
                        pickable=False,
                    ),
                ]
            )

    latitude, longitude = view_center

    return pdk.Deck(
        layers=layers,
        initial_view_state=pdk.ViewState(
            latitude=latitude,
            longitude=longitude,
            zoom=view_zoom,
            pitch=0,
            bearing=0,
        ),
        map_provider="carto",
        map_style="light",
        tooltip={"text": "{tooltip_text}"},
    )


def compact_map_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """ブラウザーへ不要なOSMタグを送らず、広域表示の転送量を抑える。"""
    compact: list[dict[str, Any]] = []
    for row in rows:
        map_row = {key: value for key, value in row.items() if key in MAP_ROW_FIELDS}
        # 色は表示時に速度から求め、再生成前のParquetに保存された旧配色を引きずらない。
        base_color = speed_color(row.get("speed_kmh"))
        if row.get("basis") == "statutory_inference":
            map_row["color"] = [*base_color[:3], 75]
            map_row["line_width"] = 2
            status_label = "推定候補・未確認"
        elif row.get("basis") == "human_observation":
            map_row["color"] = [*base_color[:3], 180]
            map_row["line_width"] = 3
            status_label = "人間が道路構造を確認"
        else:
            map_row["color"] = base_color
            map_row["line_width"] = 6 if (row.get("speed_kmh") or 0) >= 70 else 4
            if row.get("basis") == "manual":
                status_label = "人間が確認済み"
            elif row.get("basis") == "unknown":
                status_label = "速度データなし"
            else:
                status_label = "原典データ由来"
        map_row["selection_color"] = [*base_color[:3], 255]
        map_row["path"] = [[round(point[0], 6), round(point[1], 6)] for point in row["path"]]
        map_row["tooltip_text"] = (
            f"【{status_label}】\n{row['road_label']}\n最高速度: {row['speed_label']}\n"
            f"根拠: {row['basis_label']}\n確度: {row['confidence_label']}\n{row['reason']}"
        )
        compact.append(map_row)
    return compact


def overrides_as_csv(store: OverrideStore) -> bytes:
    output = io.StringIO(newline="")
    rows = store.list_all()
    fieldnames = [
        "segment_id",
        "osm_way_id",
        "from_node",
        "to_node",
        "road_name",
        "speed_kmh",
        "evidence_type",
        "evidence_url",
        "note",
        "midpoint_lat",
        "midpoint_lon",
        "created_at",
        "updated_at",
    ]
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue().encode("utf-8-sig")


def observations_as_csv(store: OverrideStore) -> bytes:
    output = io.StringIO(newline="")
    rows = store.list_observations()
    fieldnames = [
        "segment_id",
        "osm_way_id",
        "from_node",
        "to_node",
        "road_name",
        "observed_feature",
        "sign_status",
        "evidence_type",
        "evidence_url",
        "note",
        "midpoint_lat",
        "midpoint_lon",
        "created_at",
        "updated_at",
    ]
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue().encode("utf-8-sig")


def edit_panel(
    store: OverrideStore,
    segment: dict[str, Any] | None,
    selected_segments: list[dict[str, Any]] | None = None,
) -> None:
    st.subheader("道路の確認・補正")
    if not segment:
        st.info("地図上の道路をクリックすると、速度標識または道路構造を登録できます。")
        return

    segment_id = str(segment["segment_id"])
    targets = selected_segments or [segment]
    existing = store.get(segment_id)
    existing_observation = store.get_observation(segment_id)
    st.write(f"**{segment.get('road_label', '名称なし')}**")
    st.caption(
        f"OSM way {segment.get('osm_way_id')} / {segment_id} / "
        f"現在の判定: {segment.get('speed_label')}（{segment.get('basis_label')}）"
    )
    if len(targets) > 1:
        st.caption(f"連続する同一判定の {len(targets):,} セグメントへ一括登録します。")
    entry_types = ["速度標識による補正", "道路構造の観測"]
    entry_type = st.radio(
        "登録する内容",
        entry_types,
        index=(
            1
            if (existing_observation or segment.get("basis") == "statutory_inference")
            and not existing
            else 0
        ),
        horizontal=True,
        key=f"entry-type-{segment_id}",
    )

    if entry_type == "速度標識による補正":
        st.caption("速度標識で確認した数値を直接保存し、すべての判定より優先します。")
        default_speed = (
            int(existing["speed_kmh"]) if existing else int(segment.get("speed_kmh") or 30)
        )
        evidence_choices = [
            "現地で標識を確認",
            "写真で確認",
            "ストリートビュー等で確認",
            "その他",
        ]
        with st.form(f"override-form-{segment_id}"):
            speed = st.number_input(
                "最高速度 (km/h)", min_value=5, max_value=130, value=default_speed, step=5
            )
            evidence_type = st.selectbox(
                "確認方法",
                evidence_choices,
                index=(
                    evidence_choices.index(existing["evidence_type"])
                    if existing and existing.get("evidence_type") in evidence_choices
                    else 0
                ),
            )
            evidence_url = st.text_input(
                "証拠URL（任意）", value=existing.get("evidence_url", "") if existing else ""
            )
            note = st.text_area("メモ（任意）", value=existing.get("note", "") if existing else "")
            submitted = st.form_submit_button("速度標識の値を保存", type="primary")

        if submitted:
            for target in targets:
                path = target.get("path") or []
                midpoint_lon = sum(point[0] for point in path) / len(path) if path else None
                midpoint_lat = sum(point[1] for point in path) / len(path) if path else None
                store.upsert(
                    segment_id=str(target["segment_id"]),
                    osm_way_id=int(target["osm_way_id"]),
                    from_node=str(target["from_node"]),
                    to_node=str(target["to_node"]),
                    road_name=str(target.get("road_name") or ""),
                    speed_kmh=int(speed),
                    evidence_type=evidence_type,
                    evidence_url=evidence_url.strip(),
                    note=note.strip(),
                    midpoint_lat=midpoint_lat,
                    midpoint_lon=midpoint_lon,
                )
            st.success(f"速度標識の補正を {len(targets):,} セグメントへ保存しました。")
            st.rerun()

        if existing and st.button("この速度補正を削除", type="secondary"):
            store.delete(segment_id)
            st.success("速度補正を削除しました。")
            st.rerun()
        return

    feature_options = {
        "中央線を確認": "center_line",
        "車両通行帯を確認": "traffic_lanes",
        "中央分離帯・上下線分離を確認": "direction_separation",
        "中央線・車両通行帯・上下線分離がないことを確認": "no_center_line",
    }
    feature_labels = list(feature_options)
    existing_feature = (
        existing_observation.get("observed_feature") if existing_observation else None
    )
    feature_index = next(
        (
            index
            for index, label in enumerate(feature_labels)
            if feature_options[label] == existing_feature
        ),
        0,
    )
    sign_options = {
        "未確認": "not_checked",
        "選択した区間内に速度標識がないことを確認": "none_in_selected_range",
    }
    existing_sign = existing_observation.get("sign_status") if existing_observation else None
    sign_labels = list(sign_options)
    sign_index = next(
        (index for index, label in enumerate(sign_labels) if sign_options[label] == existing_sign),
        0,
    )
    observation_methods = [
        "現地で確認",
        "写真で確認",
        "Google Street Viewで確認",
        "Mapillaryで確認",
        "その他",
    ]
    st.caption(
        "道路構造という観測事実を保存します。アプリが30または60の法定速度候補を算出し、"
        "JARTIC・OSM・速度標識の指定値があればそちらを優先します。"
    )
    if existing:
        st.warning("速度標識による補正が登録済みのため、道路構造の観測より優先されます。")
    with st.form(f"observation-form-{segment_id}"):
        feature_label = st.selectbox("確認した道路構造", feature_labels, index=feature_index)
        sign_label = st.selectbox("指定速度標識の確認状況", sign_labels, index=sign_index)
        observation_method = st.selectbox(
            "確認手段",
            observation_methods,
            index=(
                observation_methods.index(existing_observation["evidence_type"])
                if existing_observation
                and existing_observation.get("evidence_type") in observation_methods
                else 0
            ),
        )
        observation_url = st.text_input(
            "証拠URL（任意）",
            value=existing_observation.get("evidence_url", "") if existing_observation else "",
        )
        observation_note = st.text_area(
            "メモ（任意）",
            value=existing_observation.get("note", "") if existing_observation else "",
        )
        observation_submitted = st.form_submit_button("道路構造の観測を保存", type="primary")

    if observation_submitted:
        for target in targets:
            path = target.get("path") or []
            midpoint_lon = sum(point[0] for point in path) / len(path) if path else None
            midpoint_lat = sum(point[1] for point in path) / len(path) if path else None
            store.upsert_observation(
                segment_id=str(target["segment_id"]),
                osm_way_id=int(target["osm_way_id"]),
                from_node=str(target["from_node"]),
                to_node=str(target["to_node"]),
                road_name=str(target.get("road_name") or ""),
                observed_feature=feature_options[feature_label],
                sign_status=sign_options[sign_label],
                evidence_type=observation_method,
                evidence_url=observation_url.strip(),
                note=observation_note.strip(),
                midpoint_lat=midpoint_lat,
                midpoint_lon=midpoint_lon,
            )
        st.success(f"道路構造の観測を {len(targets):,} セグメントへ保存しました。")
        st.rerun()

    if existing_observation and st.button("この道路構造の観測を削除", type="secondary"):
        store.delete_observation(segment_id)
        st.success("道路構造の観測を削除しました。")
        st.rerun()


def jartic_detail_panel(feature: dict[str, Any] | None) -> None:
    if not feature:
        return
    st.subheader("JARTIC指定速度の詳細")
    speed_label = feature.get("speed_label", "速度不明")
    regulation_name = feature.get("regulation_name", "指定速度")
    st.write(f"**{speed_label} — {regulation_name}**")
    details = [
        ("規制内容", feature.get("content")),
        ("規制条件", feature.get("condition")),
        ("意思決定日", feature.get("decision_date")),
        ("改正日", feature.get("revision_date")),
        ("データ更新日", feature.get("updated_date")),
        ("識別子", feature.get("jartic_id")),
    ]
    for label, value in details:
        if value:
            st.write(f"{label}: {value}")
    st.caption(
        "これはJARTICが配布した元の規制線・規制区域です。下のOSM道路をクリックして"
        "手動補正する場合は、サイドバーの検証用表示を一時的にオフにしてください。"
    )


def main() -> None:
    st.title("道路最高速度マップ")
    st.caption(
        "指定速度・法定速度の推定・手動確認を区別して表示するPoCです。"
        "実際の運転では現地の標識・道路標示に従ってください。"
    )

    store = OverrideStore(OVERRIDE_DB)
    with st.sidebar:
        st.header("表示範囲")
        preset_name = st.selectbox("エリア", list(MAP_PRESETS), index=0)
        preset = MAP_PRESETS[preset_name]
        st.caption(f"BBox: {', '.join(str(value) for value in preset.bbox)}")
        if preset.prepared_dataset:
            st.caption("道路データ: ローカル事前生成Parquet")
        else:
            tile_count = len(bbox_tiles(preset.bbox))
            st.caption(f"OpenStreetMap取得単位: {tile_count} 分割")
        if preset.note:
            st.warning(preset.note)
        st.divider()
        st.header("描画モード")
        drawing_mode = st.radio(
            "速度の判定材料",
            ["データのみ", "知見を追加", "推定候補をレビュー"],
            help=(
                "データのみ: JARTIC指定速度とOSMの数値maxspeed。"
                "知見を追加: 確認根拠付きの手動補正も使用。"
                "推定候補をレビュー: OSMタグから推定した候補も表示。"
            ),
        )
        include_manual = drawing_mode != "データのみ"
        include_inference = drawing_mode == "推定候補をレビュー"
        if include_inference:
            st.caption("手動補正と、未確認の道路構造推定を上乗せします。")
        elif include_manual:
            st.caption("確認根拠付きの手動補正だけを上乗せします。")
        else:
            st.caption("手動補正・道路構造からの速度推定は使用しません。")
        refresh = st.button("OpenStreetMapを再取得", disabled=bool(preset.prepared_dataset))
        if preset.prepared_dataset:
            st.caption("全域データの更新は前処理コマンドで行います。")
        show_jartic = st.checkbox(
            "JARTIC配布元の規制線を表示（検証用）",
            value=False,
            help=(
                "JARTICが配布した元の線・区域を、そのまま地図へ重ねます。"
                "OFFでも、JARTICをOSM道路へ自動対応した速度判定は表示されます。"
            ),
        )
        refresh_jartic = st.button("JARTICを再取得", disabled=bool(preset.prepared_dataset))
        st.divider()
        st.header("表示フィルター")
        show_bases = st.multiselect(
            "根拠",
            [
                "manual",
                "human_observation",
                "jartic",
                "osm",
                "statutory_inference",
                "unknown",
            ],
            default=[
                "manual",
                "human_observation",
                "jartic",
                "osm",
                "statutory_inference",
                "unknown",
            ],
            format_func={
                "manual": "速度標識を人間が確認",
                "human_observation": "道路構造を人間が確認",
                "jartic": "JARTIC自動対応",
                "osm": "OSM指定値",
                "statutory_inference": "法定速度の推定",
                "unknown": "不明",
            }.get,
        )
        st.divider()
        st.download_button(
            "速度標識の補正をCSV出力",
            data=overrides_as_csv(store),
            file_name="road_speed_overrides.csv",
            mime="text/csv",
        )
        st.download_button(
            "道路構造の観測をCSV出力",
            data=observations_as_csv(store),
            file_name="road_structure_observations.csv",
            mime="text/csv",
        )

    using_prepared_dataset = bool(preset.prepared_dataset)
    if preset.prepared_dataset:
        dataset = ROOT / preset.prepared_dataset
        if not dataset.exists():
            st.error(f"{preset_name}の事前生成データがまだありません。")
            st.code(
                f'uv run python scripts/prepare_regions.py --region "{preset_name}"',
                language="powershell",
            )
            st.stop()
        with st.spinner("事前生成済み道路データを読み込んでいます…"):
            segments = cached_load_prepared(str(dataset), dataset.stat().st_mtime_ns)
    else:
        try:
            spinner_text = (
                "道路データを取得しています…" if refresh else "道路データを読み込んでいます…"
            )
            progress = st.progress(0, text="OpenStreetMapキャッシュを確認しています…")

            def update_progress(current: int, total: int) -> None:
                progress.progress(
                    current / total,
                    text=f"OpenStreetMap道路データを取得中: {current}/{total}",
                )

            with st.spinner(spinner_text):
                snapshot = fetch_overpass_snapshot(
                    preset.bbox,
                    CACHE_DIR,
                    refresh=refresh,
                    progress_callback=update_progress,
                )
                segments = cached_load_segments(str(snapshot), snapshot.stat().st_mtime_ns)
            progress.empty()
        except OverpassError as exc:
            st.error(str(exc))
            st.info("しばらく待って再取得するか、別の表示範囲を選択してください。")
            st.stop()

    jartic_lines: list[dict[str, Any]] = []
    jartic_areas: list[dict[str, Any]] = []
    jartic_metadata: dict[str, str] = {}
    try:
        with st.spinner("JARTIC指定速度を読み込んでいます…"):
            archive, jartic_metadata = fetch_jartic_snapshot(
                CACHE_DIR / "jartic", refresh=refresh_jartic
            )
            jartic_lines, jartic_areas = load_jartic_speed_features(archive, preset.bbox)
    except JarticError as exc:
        st.warning(f"JARTICデータは利用できません: {exc}")

    if using_prepared_dataset:
        jartic_match_count = sum(row.get("basis") == "jartic" for row in segments)
        base_rows = segments if include_inference else source_data_only(segments)
        enriched = (
            apply_human_knowledge(
                base_rows,
                store.as_mapping(),
                store.observations_mapping(),
            )
            if include_manual
            else base_rows
        )
    else:
        with st.spinner("JARTIC指定区間をOSM道路へ対応付けています…"):
            jartic_matches = cached_match_jartic(segments, jartic_lines, jartic_areas, preset.bbox)
        jartic_match_count = len(jartic_matches)
        base_rows = enrich_segments(segments, {}, jartic_matches, infer_statutory=include_inference)
        enriched = (
            apply_human_knowledge(
                base_rows,
                store.as_mapping(),
                store.observations_mapping(),
            )
            if include_manual
            else base_rows
        )
    visible = [row for row in enriched if row["basis"] in show_bases]

    bases = ["manual", "human_observation", "jartic", "osm", "statutory_inference", "unknown"]
    counts = {basis: sum(row["basis"] == basis for row in enriched) for basis in bases}
    metric_columns = st.columns(6)
    metric_columns[0].metric("道路セグメント", f"{len(enriched):,}")
    metric_columns[1].metric("JARTIC自動対応", f"{counts['jartic']:,}")
    human_count = counts["manual"] + counts["human_observation"]
    metric_columns[2].metric("人間確認", f"{human_count:,}")
    metric_columns[3].metric("OSM指定値", f"{counts['osm']:,}")
    metric_columns[4].metric("法定速度の推定", f"{counts['statutory_inference']:,}")
    metric_columns[5].metric("不明", f"{counts['unknown']:,}")
    if drawing_mode == "データのみ":
        st.info(
            "データのみモード: JARTIC指定速度とOSMに数値で記録されたmaxspeedだけを"
            "着色しています。灰色は速度値のない道路です。"
        )
    elif drawing_mode == "知見を追加":
        st.info(
            "知見を追加: 原典データに、速度標識の補正と、人間が確認した道路構造からの"
            "法定速度候補を上乗せしています。未確認の機械推定は含みません。"
        )

    legend = "　".join(
        f"<span style='color:rgb({SPEED_COLORS[color_key][0]},"
        f"{SPEED_COLORS[color_key][1]},{SPEED_COLORS[color_key][2]})'>●</span> {label}"
        for label, color_key in SPEED_LEGEND
    )
    legend += "　<span style='color:rgb(130,130,130)'>●</span> 不明"
    st.markdown(legend, unsafe_allow_html=True)
    with st.expander("表示の見方・データ詳細", expanded=False):
        st.caption("ホバー中は濃いグレー、選択中は本来の速度色を黒い縁取りで強調します。")
        st.caption("70 km/h以上の確定線は、高速帯を見分けやすくするため太く表示します。")
        if include_inference:
            st.caption(
                "線の意味: 太い不透明線＝原典値・人間による確認 / "
                "細い半透明線＝未確認の推定候補（速度にかかわらず共通）"
            )
        st.caption(
            f"JARTIC原典: {len(jartic_lines) + len(jartic_areas):,} 区間・区域 / "
            f"OSMへの自動対応: {jartic_match_count:,} セグメント / "
            f"速度標識確認: {counts['manual']:,} / "
            f"道路構造確認: {counts['human_observation']:,}"
        )

    selected_id = st.session_state.get("selected_segment_id")
    displayed_lines = jartic_lines if show_jartic else []
    displayed_areas = jartic_areas if show_jartic else []
    display_rows = (
        merge_contiguous_segments(visible, simplify_tolerance=0.00001)
        if using_prepared_dataset
        else visible
    )
    display_groups = {
        row["segment_id"]: row.get("segment_ids", [row["segment_id"]]) for row in display_rows
    }
    deck = render_deck(
        compact_map_rows(display_rows),
        selected_id,
        displayed_lines,
        displayed_areas,
        preset.center,
        preset.zoom,
    )
    event = st.pydeck_chart(
        deck,
        on_select="rerun",
        selection_mode="single-object",
        key="road-speed-map",
        height=650,
    )
    selected_layer, clicked = selected_object(event)
    if clicked and selected_layer in {ROAD_LAYER_ID, INFERRED_ROAD_LAYER_ID}:
        st.session_state.selected_segment_id = clicked["segment_id"]
        st.session_state.selected_segment_ids = display_groups.get(
            clicked["segment_id"], [clicked["segment_id"]]
        )
        st.session_state.selected_jartic_id = None
        selected_id = clicked["segment_id"]
    elif clicked and selected_layer in {JARTIC_LINE_LAYER_ID, JARTIC_ZONE_LAYER_ID}:
        st.session_state.selected_jartic_id = clicked["jartic_id"]
        st.session_state.selected_segment_id = None
        st.session_state.selected_segment_ids = []
        selected_id = None

    selected_jartic_id = st.session_state.get("selected_jartic_id")
    selected_jartic = next(
        (
            feature
            for feature in [*jartic_lines, *jartic_areas]
            if feature["jartic_id"] == selected_jartic_id
        ),
        None,
    )
    jartic_detail_panel(selected_jartic)
    rows_by_id = {row["segment_id"]: row for row in enriched}
    selected = rows_by_id.get(selected_id)
    selected_segments = [
        rows_by_id[segment_id]
        for segment_id in st.session_state.get("selected_segment_ids", [])
        if segment_id in rows_by_id
    ]
    edit_panel(store, selected, selected_segments)

    with st.expander("判定方法と制約"):
        st.markdown(
            """
- 速度標識の手動補正を最優先し、次にJARTIC自動対応、OSMの数値 `maxspeed` を使います。
- 指定速度値がない道路では、人間が確認した道路構造、OSMタグからの推定の順に使います。
- 「データのみ」ではJARTIC指定速度とOSMの数値 `maxspeed` だけを使います。
  手動補正と法定速度推定は除外します。
- 「知見を追加」では速度標識の補正と、人間が確認した道路構造を上乗せします。
- 「推定候補をレビュー」では、道路構造・道路種別タグからの法定速度推定も表示します。
  推定線をクリックして根拠付きで保存すると、手動確認済みに昇格できます。
- JARTIC配布元の規制線・区域は検証用に重ねられ、ホバー・クリックで内容を確認できます。
  OFFにしても、OSM道路へ自動対応済みのJARTIC速度判定は残ります。
- JARTICとOSMは15 m以内かつ方向差25度以内の近接判定で自動対応します。
  厳密な道路IDの一致ではないため確度は「中」とし、交差点や並行道路では誤対応の可能性があります。
- 推定は法的な確定情報ではありません。中央線・車両通行帯をOSM属性だけで完全には判定できません。
- `residential` などの道路種別だけでは30 km/hとみなしません。
  「推定候補をレビュー」でのみ、中央線等が未確認の30 km/h候補として表示します。
- 高速道路、方向別・時間帯別速度など、単一速度で安全に表現できない道路は原則「不明」にします。
- 方向・時間条件はまだ速度判定へ反映していません。実際の運転では現地標識・道路標示が優先です。
"""
        )
    source_month = jartic_metadata.get("target_month", "取得データ")
    distribution = " / 配布: Geofabrik" if using_prepared_dataset else ""
    st.caption(
        f"道路データ: © OpenStreetMap contributors (ODbL){distribution} / "
        "交通規制情報: 「交通規制情報」"
        f"公益財団法人日本道路交通情報センター（{source_month}）を加工して作成"
    )


if __name__ == "__main__":
    main()
