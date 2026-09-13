import tempfile
import unittest
from pathlib import Path

from road_speed_map.overrides import OverrideStore


class OverrideStoreTests(unittest.TestCase):
    def test_upsert_and_delete(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = OverrideStore(Path(directory) / "overrides.sqlite3")
            values = {
                "segment_id": "osm:1:2:3",
                "osm_way_id": 1,
                "from_node": "2",
                "to_node": "3",
                "road_name": "テスト通り",
                "speed_kmh": 30,
                "evidence_type": "現地で標識を確認",
                "evidence_url": "",
                "note": "北側の標識",
                "midpoint_lat": 43.0,
                "midpoint_lon": 141.0,
            }
            store.upsert(**values)
            self.assertEqual(30, store.get(values["segment_id"])["speed_kmh"])

            store.upsert(**{**values, "speed_kmh": 40})
            self.assertEqual(40, store.get(values["segment_id"])["speed_kmh"])

            store.delete(values["segment_id"])
            self.assertIsNone(store.get(values["segment_id"]))

    def test_upsert_and_delete_observation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = OverrideStore(Path(directory) / "overrides.sqlite3")
            values = {
                "segment_id": "osm:1:2:3",
                "osm_way_id": 1,
                "from_node": "2",
                "to_node": "3",
                "road_name": "テスト通り",
                "observed_feature": "center_line",
                "sign_status": "none_in_selected_range",
                "evidence_type": "Google Street Viewで確認",
                "evidence_url": "https://example.com/evidence",
                "note": "中央線あり",
                "midpoint_lat": 43.0,
                "midpoint_lon": 141.0,
            }
            store.upsert_observation(**values)
            observation = store.get_observation(values["segment_id"])
            self.assertEqual("center_line", observation["observed_feature"])
            self.assertEqual(1, len(store.observations_mapping()))

            store.delete_observation(values["segment_id"])
            self.assertIsNone(store.get_observation(values["segment_id"]))


if __name__ == "__main__":
    unittest.main()
