import unittest

from road_speed_map.display import merge_contiguous_segments


class DisplayTests(unittest.TestCase):
    def test_merges_contiguous_segments_with_same_result(self) -> None:
        rows = [
            {
                "segment_id": "osm:1:1:2",
                "osm_way_id": 1,
                "from_node": "1",
                "to_node": "2",
                "road_label": "道路",
                "path": [[141.0, 43.0], [141.1, 43.1]],
                "speed_kmh": 50,
                "basis": "jartic",
            },
            {
                "segment_id": "osm:1:2:3",
                "osm_way_id": 1,
                "from_node": "2",
                "to_node": "3",
                "road_label": "道路",
                "path": [[141.1, 43.1], [141.2, 43.2]],
                "speed_kmh": 50,
                "basis": "jartic",
            },
        ]
        merged = merge_contiguous_segments(rows)
        self.assertEqual(1, len(merged))
        self.assertEqual(["osm:1:1:2", "osm:1:2:3"], merged[0]["segment_ids"])
        self.assertEqual(3, len(merged[0]["path"]))

    def test_does_not_merge_manual_segments(self) -> None:
        rows = [
            {
                "segment_id": f"osm:1:{index}:{index + 1}",
                "osm_way_id": 1,
                "from_node": str(index),
                "to_node": str(index + 1),
                "road_label": "道路",
                "path": [[float(index), 43.0], [float(index + 1), 43.0]],
                "speed_kmh": 30,
                "basis": "manual",
            }
            for index in range(2)
        ]
        self.assertEqual(2, len(merge_contiguous_segments(rows)))

    def test_simplifies_display_path_without_losing_group_members(self) -> None:
        rows = [
            {
                "segment_id": f"osm:1:{index}:{index + 1}",
                "osm_way_id": 1,
                "from_node": str(index),
                "to_node": str(index + 1),
                "road_label": "道路",
                "path": [[141.0 + index * 0.001, 43.0], [141.001 + index * 0.001, 43.0]],
                "speed_kmh": 50,
                "basis": "osm",
            }
            for index in range(3)
        ]
        merged = merge_contiguous_segments(rows, simplify_tolerance=0.00001)
        self.assertEqual(2, len(merged[0]["path"]))
        self.assertEqual(3, len(merged[0]["segment_ids"]))


if __name__ == "__main__":
    unittest.main()
