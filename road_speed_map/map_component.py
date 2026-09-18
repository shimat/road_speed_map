from __future__ import annotations

import streamlit as st

MAP_COMPONENT_HTML = """
<div class="road-map-shell">
  <div class="road-map-canvas"></div>
  <div class="road-map-status">地図を準備しています…</div>
  <div class="road-map-hover" hidden></div>
</div>
"""

MAP_COMPONENT_CSS = """
.road-map-shell { position: relative; width: 100%; height: 100%; min-height: 650px; overflow: hidden;
  border: 1px solid var(--st-border-color); border-radius: .5rem; background: #edf0ed; }
.road-map-canvas { position: absolute; inset: 0; }
.road-map-status { position: absolute; inset: 0; display: grid; place-items: center; z-index: 4;
  color: #263238; background: rgba(245,247,245,.92); font-weight: 600; }
.road-map-status[hidden] { display: none; }
.road-map-hover { position: absolute; left: .75rem; bottom: .75rem; z-index: 3; max-width: min(520px, 75%);
  padding: .45rem .65rem; border-radius: .35rem; color: #fff; background: rgba(35,42,48,.92);
  font-size: .82rem; line-height: 1.35; pointer-events: none; white-space: pre-line; }
.road-editor-popup { top: 12px !important; left: 12px !important; right: auto !important; bottom: auto !important;
  max-width: calc(100% - 72px) !important; transform: none !important; }
.road-editor-popup .maplibregl-popup-tip { display: none; }
.maplibregl-popup-content { max-height: min(450px, calc(100vh - 96px)); overflow: hidden; }
.road-edit { box-sizing: border-box; width: 340px; max-width: calc(100vw - 64px);
  max-height: min(430px, calc(100vh - 116px)); padding-right: .4rem; overflow-y: scroll;
  scrollbar-gutter: stable; scrollbar-color: #8b949e #eef0f2; scrollbar-width: auto;
  color: #202124; font: 14px/1.35 sans-serif; }
.road-edit::-webkit-scrollbar { width: 11px; }
.road-edit::-webkit-scrollbar-track { background: #eef0f2; border-radius: 6px; }
.road-edit::-webkit-scrollbar-thumb { border: 2px solid #eef0f2; border-radius: 6px; background: #8b949e; }
.road-edit .title-row { display: flex; gap: .5rem; align-items: flex-start; }
.road-edit h3 { margin: 0 0 .25rem; font-size: 1rem; }
.road-edit .close { flex: 0 0 auto; margin: -.35rem -.35rem 0 auto; padding: .1rem .4rem;
  border: 0; color: #4b5563; background: transparent; font-size: 1.35rem; line-height: 1; cursor: pointer; }
.road-edit .close:hover { color: #111827; background: #eef0f2; }
.road-edit .summary { margin: 0 0 .65rem; color: #4b5563; white-space: pre-line; }
.road-edit label { display: block; margin: .5rem 0 .15rem; font-size: .78rem; font-weight: 700; }
.road-edit input, .road-edit select, .road-edit textarea { box-sizing: border-box; width: 100%; padding: .38rem;
  border: 1px solid #b7bdc5; border-radius: .25rem; color: #202124; background: white; }
.road-edit textarea { min-height: 56px; resize: vertical; }
.road-edit .actions { position: sticky; bottom: 0; display: flex; gap: .45rem; align-items: center;
  margin: .75rem -.25rem 0; padding: .55rem .25rem .1rem; background: rgba(255,255,255,.97); }
.road-edit button { padding: .42rem .75rem; border: 1px solid #aab0b7; border-radius: .3rem;
  cursor: pointer; background: #f4f5f6; }
.road-edit button.primary { border-color: #1769aa; color: white; background: #1976d2; font-weight: 700; }
.road-edit button.danger { margin-left: auto; color: #a51d25; }
.road-edit .saving { color: #455a64; font-size: .8rem; }
"""

MAP_COMPONENT_JS = r"""
const MAPLIBRE_VERSION = "6.1.0";

function maplibreCssUrl() {
  return `https://unpkg.com/maplibre-gl@${MAPLIBRE_VERSION}/dist/maplibre-gl.css`;
}

async function loadMapLibre(parentElement) {
  if (!parentElement.querySelector("link[data-road-maplibre]")) {
    const link = document.createElement("link");
    link.rel = "stylesheet";
    link.href = maplibreCssUrl();
    link.dataset.roadMaplibre = "true";
    parentElement.prepend(link);
  }
  if (!globalThis.__roadMaplibrePromise) {
    globalThis.__roadMaplibrePromise = import(
      `https://unpkg.com/maplibre-gl@${MAPLIBRE_VERSION}/dist/maplibre-gl.mjs`
    );
  }
  return globalThis.__roadMaplibrePromise;
}

function byteArray(value) {
  if (value instanceof Uint8Array) return value;
  if (value instanceof ArrayBuffer) return new Uint8Array(value);
  if (ArrayBuffer.isView(value)) return new Uint8Array(value.buffer, value.byteOffset, value.byteLength);
  if (Array.isArray(value)) return new Uint8Array(value);
  if (value?.data && Array.isArray(value.data)) return new Uint8Array(value.data);
  throw new Error("道路データのバイナリ形式を読み取れませんでした");
}

async function decodePayload(data) {
  const bytes = byteArray(data);
  if (typeof DecompressionStream === "undefined") {
    throw new Error("このブラウザーはgzip展開に対応していません");
  }
  const stream = new Blob([bytes]).stream().pipeThrough(new DecompressionStream("gzip"));
  return JSON.parse(await new Response(stream).text());
}

function baseStyle() {
  return {
    version: 8,
    sources: {
      osm: {
        type: "raster",
        tiles: ["https://tile.openstreetmap.org/{z}/{x}/{y}.png"],
        tileSize: 256,
        attribution: "© OpenStreetMap contributors"
      }
    },
    layers: [{
      id: "osm",
      type: "raster",
      source: "osm",
      paint: {
        "raster-opacity": 0.65,
        "raster-saturation": -0.65,
        "raster-contrast": -0.08,
        "raster-brightness-max": 0.96
      }
    }]
  };
}

function option(select, value, label) {
  const item = document.createElement("option");
  item.value = value;
  item.textContent = label;
  select.append(item);
}

function fixedField(form, selector, value) {
  const field = form.querySelector(selector);
  field.value = value ?? "";
  return field;
}

function popupForm(maplibregl, state, feature, lngLat) {
  const p = feature.properties;
  const root = document.createElement("div");
  root.className = "road-edit";
  root.innerHTML = `
    <div class="title-row"><h3 class="road-name"></h3>
      <button class="close" type="button" aria-label="保存せず閉じる" title="保存せず閉じる">×</button></div>
    <p class="summary"></p>
    <form>
      <label>登録する内容</label><select name="kind"></select>
      <section data-kind="speed">
        <label>最高速度 (km/h)</label><input name="speed" type="number" min="5" max="130" step="5">
        <label>確認方法</label><select name="speedEvidence"></select>
      </section>
      <section data-kind="observation">
        <label>確認した道路構造</label><select name="feature"></select>
        <label>指定速度標識の確認状況</label><select name="sign"></select>
        <label>確認手段</label><select name="observationEvidence"></select>
      </section>
      <label>証拠URL（任意）</label><input name="url" type="url">
      <label>メモ（任意）</label><textarea name="note"></textarea>
      <div class="actions"><button class="primary" type="submit">保存して反映</button>
        <span class="saving"></span><button class="danger" type="button" hidden>削除</button></div>
    </form>`;
  root.querySelector(".road-name").textContent = p.road;
  root.querySelector(".summary").textContent =
    `現在: ${p.speed_label}\n根拠: ${p.basis_label}（確度 ${p.confidence}）\n${p.reason}`;

  const form = root.querySelector("form");
  const kind = form.elements.kind;
  option(kind, "speed", "速度標識による補正");
  option(kind, "observation", "道路構造の観測");
  kind.value = p.observation_feature && !p.override_speed ? "observation" : "speed";

  fixedField(form, "[name=speed]", p.override_speed ?? p.speed ?? 30);
  const speedEvidence = form.elements.speedEvidence;
  ["現地で標識を確認", "写真で確認", "ストリートビュー等で確認", "その他"]
    .forEach(x => option(speedEvidence, x, x));
  speedEvidence.value = p.override_evidence || "現地で標識を確認";

  const structure = form.elements.feature;
  option(structure, "center_line", "中央線を確認");
  option(structure, "traffic_lanes", "車両通行帯を確認");
  option(structure, "direction_separation", "中央分離帯・上下線分離を確認");
  option(structure, "no_center_line", "中央線・車両通行帯・上下線分離なし");
  structure.value = p.observation_feature || "center_line";

  const sign = form.elements.sign;
  option(sign, "not_checked", "未確認");
  option(sign, "none_in_selected_range", "選択区間内に速度標識なしを確認");
  sign.value = p.observation_sign || "not_checked";

  const observationEvidence = form.elements.observationEvidence;
  ["現地で確認", "写真で確認", "Google Street Viewで確認", "Mapillaryで確認", "その他"]
    .forEach(x => option(observationEvidence, x, x));
  observationEvidence.value = p.observation_evidence || "現地で確認";

  function syncKind() {
    const speed = kind.value === "speed";
    form.querySelector("[data-kind=speed]").hidden = !speed;
    form.querySelector("[data-kind=observation]").hidden = speed;
    form.elements.url.value = speed ? (p.override_url || "") : (p.observation_url || "");
    form.elements.note.value = speed ? (p.override_note || "") : (p.observation_note || "");
    const remove = form.querySelector(".danger");
    remove.hidden = speed ? !p.override_speed : !p.observation_feature;
    remove.textContent = speed ? "速度補正を削除" : "構造観測を削除";
  }
  kind.onchange = syncKind;
  syncKind();

  function send(payload) {
    const saving = form.querySelector(".saving");
    saving.textContent = "保存中…";
    form.querySelectorAll("button, input, select, textarea").forEach(x => x.disabled = true);
    state.setTriggerValue("save", { segment_id: p.id, ...payload });
  }
  form.onsubmit = event => {
    event.preventDefault();
    const common = { evidence_url: form.elements.url.value, note: form.elements.note.value };
    if (kind.value === "speed") {
      send({ action: "save_speed", speed_kmh: Number(form.elements.speed.value),
        evidence_type: speedEvidence.value, ...common });
    } else {
      send({ action: "save_observation", observed_feature: structure.value,
        sign_status: sign.value, evidence_type: observationEvidence.value, ...common });
    }
  };
  form.querySelector(".danger").onclick = () => send({
    action: kind.value === "speed" ? "delete_speed" : "delete_observation"
  });

  const popup = new maplibregl.Popup({
    className: "road-editor-popup", closeButton: false, closeOnClick: true, maxWidth: "380px"
  })
    .setLngLat(lngLat).setDOMContent(root).addTo(state.map);
  state.popup = popup;
  const closePopup = () => popup.remove();
  const escapeHandler = event => {
    if (event.key === "Escape") closePopup();
  };
  root.querySelector(".close").onclick = closePopup;
  document.addEventListener("keydown", escapeHandler);
  popup.on("close", () => {
    document.removeEventListener("keydown", escapeHandler);
    if (state.popup !== popup) return;
    state.popup = null;
    state.selectedId = null;
    if (state.map.getLayer("selected-road-casing")) {
      state.map.setFilter("selected-road-casing", ["==", ["get", "id"], ""]);
    }
  });
}

function addRoadLayers(state, geojson) {
  const map = state.map;
  map.addSource("roads", { type: "geojson", data: geojson, promoteId: "id" });
  map.addLayer({
    id: "selected-road-casing", type: "line", source: "roads", filter: ["==", ["get", "id"], ""],
    paint: { "line-color": "#111", "line-width": ["+", ["get", "width"], 4], "line-opacity": 1 }
  });
  map.addLayer({
    id: "roads", type: "line", source: "roads",
    paint: {
      "line-color": ["case", ["boolean", ["feature-state", "hover"], false], "#424242", ["get", "color"]],
      "line-width": ["get", "width"], "line-opacity": ["get", "opacity"]
    }
  });
  map.addLayer({
    id: "roads-hit", type: "line", source: "roads",
    paint: { "line-color": "#000", "line-width": ["max", 12, ["+", ["get", "width"], 6]],
      "line-opacity": 0.01 }
  });
}

function bindRoadEvents(maplibregl, state) {
  const map = state.map;
  map.on("mousemove", "roads-hit", event => {
    const feature = event.features?.[0];
    if (!feature) return;
    if (state.hoveredId && state.hoveredId !== feature.id) {
      map.setFeatureState({ source: "roads", id: state.hoveredId }, { hover: false });
    }
    state.hoveredId = feature.id;
    map.setFeatureState({ source: "roads", id: feature.id }, { hover: true });
    map.getCanvas().style.cursor = "pointer";
    const p = feature.properties;
    state.hover.hidden = false;
    state.hover.textContent = `${p.road}\n${p.speed_label} / ${p.basis_label}`;
  });
  map.on("mouseleave", "roads-hit", () => {
    if (state.hoveredId) map.setFeatureState({ source: "roads", id: state.hoveredId }, { hover: false });
    state.hoveredId = null;
    map.getCanvas().style.cursor = "";
    state.hover.hidden = true;
  });
  map.on("click", "roads-hit", event => {
    const feature = event.features?.[0];
    if (!feature) return;
    if (state.popup) state.popup.remove();
    state.selectedId = String(feature.properties.id);
    map.setFilter("selected-road-casing", ["==", ["get", "id"], state.selectedId]);
    popupForm(maplibregl, state, feature, event.lngLat);
  });
}

export default async function(component) {
  const { data, parentElement, setTriggerValue } = component;
  const status = parentElement.querySelector(".road-map-status");
  try {
    status.hidden = false;
    status.textContent = "道路データを展開しています…";
    const [payload, maplibregl] = await Promise.all([decodePayload(data), loadMapLibre(parentElement)]);
    let state = parentElement.__roadMapState;
    const existingCanvas = parentElement.querySelector("canvas.maplibregl-canvas");
    if (state?.map && existingCanvas) {
      state.setTriggerValue = setTriggerValue;
      const source = state.map.getSource("roads");
      if (source) source.setData(payload.geojson);
      status.hidden = true;
      state.map.resize();
      return;
    }
    if (state?.map) {
      try { state.map.remove(); } catch (error) { console.debug("Discarding detached map", error); }
    }

    state = {
      map: null, popup: null, hoveredId: null, selectedId: null, setTriggerValue,
      hover: parentElement.querySelector(".road-map-hover")
    };
    parentElement.__roadMapState = state;
    state.map = new maplibregl.Map({
      container: parentElement.querySelector(".road-map-canvas"), style: baseStyle(),
      center: payload.center, zoom: payload.zoom, attributionControl: true
    });
    state.map.addControl(new maplibregl.NavigationControl(), "top-right");
    state.map.on("load", () => {
      addRoadLayers(state, payload.geojson);
      bindRoadEvents(maplibregl, state);
      status.hidden = true;
    });
    state.map.on("error", event => {
      if (event?.error) console.error("Road map error", event.error);
    });
  } catch (error) {
    console.error(error);
    status.hidden = false;
    status.textContent = `MapLibre地図を表示できません: ${error.message}`;
  }
}
"""


_maplibre_editor = None


def maplibre_editor(**kwargs):
    """MapLibre編集コンポーネントを遅延登録して描画する。"""
    global _maplibre_editor
    if _maplibre_editor is None:
        _maplibre_editor = st.components.v2.component(
            "road_speed_map.maplibre_editor",
            html=MAP_COMPONENT_HTML,
            css=MAP_COMPONENT_CSS,
            js=MAP_COMPONENT_JS,
        )
    return _maplibre_editor(**kwargs)
