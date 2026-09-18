import gzip
import json
import tempfile
import unittest
from pathlib import Path

from road_speed_map.maplibre import apply_map_edit, encode_map_payload
from road_speed_map.overrides import OverrideStore


def sample_row(segment_id: str = "osm:1:10:11") -> dict:
    return {
        "segment_id": segment_id,
        "osm_way_id": 1,
        "from_node": "10",
        "to_node": "11",
        "road_name": "試験通",
        "road_label": "試験通（residential）",
        "path": [[141.0, 43.0], [141.01, 43.01]],
        "speed_kmh": 30,
        "speed_label": "30 km/h候補",
        "basis": "statutory_inference",
        "basis_label": "道路構造から法定速度を推定",
        "confidence_label": "低",
        "reason": "生活道路系の道路種別から推定",
    }


class MapLibreTests(unittest.TestCase):
    def test_payload_is_gzipped_geojson_with_edit_fields(self) -> None:
        encoded = encode_map_payload(
            [sample_row()],
            center=(43.0, 141.0),
            zoom=9,
            overrides={},
            observations={},
        )
        payload = json.loads(gzip.decompress(encoded))
        feature = payload["geojson"]["features"][0]
        self.assertEqual([141.0, 43.0], payload["center"])
        self.assertEqual("osm:1:10:11", feature["id"])
        self.assertEqual(3, feature["properties"]["width"])
        self.assertEqual(0.6, feature["properties"]["opacity"])

    def test_speed_edit_is_saved_for_every_target(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = OverrideStore(Path(temporary) / "overrides.sqlite3")
            rows = [sample_row("osm:1:10:11"), sample_row("osm:1:11:12")]
            count, _ = apply_map_edit(
                store,
                rows,
                [row["segment_id"] for row in rows],
                {
                    "action": "save_speed",
                    "speed_kmh": 40,
                    "evidence_type": "写真で確認",
                    "evidence_url": "https://example.com/photo",
                    "note": "標識あり",
                },
            )
            self.assertEqual(2, count)
            self.assertEqual(40, store.get("osm:1:10:11")["speed_kmh"])
            self.assertEqual("写真で確認", store.get("osm:1:11:12")["evidence_type"])

    def test_structure_observation_can_be_saved_and_deleted(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = OverrideStore(Path(temporary) / "overrides.sqlite3")
            row = sample_row()
            count, _ = apply_map_edit(
                store,
                [row],
                [row["segment_id"]],
                {
                    "action": "save_observation",
                    "observed_feature": "center_line",
                    "sign_status": "none_in_selected_range",
                    "evidence_type": "Google Street Viewで確認",
                },
            )
            self.assertEqual(1, count)
            self.assertEqual(
                "center_line", store.get_observation(row["segment_id"])["observed_feature"]
            )
            deleted, _ = apply_map_edit(
                store,
                [row],
                [row["segment_id"]],
                {"action": "delete_observation"},
            )
            self.assertEqual(1, deleted)
            self.assertIsNone(store.get_observation(row["segment_id"]))


if __name__ == "__main__":
    unittest.main()
