import unittest

from road_speed_map.matching import match_jartic_to_segments


class MatchingTests(unittest.TestCase):
    bbox = (43.0, 141.3, 43.1, 141.4)

    def test_matches_nearby_parallel_road(self) -> None:
        segments = [
            {
                "segment_id": "osm:1:1:2",
                "path": [[141.34, 43.06], [141.341, 43.06]],
            }
        ]
        official = [
            {
                "jartic_id": "jartic:1:0",
                "speed_kmh": 50,
                "path": [[141.34, 43.06005], [141.341, 43.06005]],
            }
        ]
        matches = match_jartic_to_segments(segments, official, [], self.bbox)
        self.assertEqual(50, matches["osm:1:1:2"]["speed_kmh"])
        self.assertLess(matches["osm:1:1:2"]["distance_m"], 6)

    def test_rejects_perpendicular_crossing(self) -> None:
        segments = [
            {
                "segment_id": "osm:1:1:2",
                "path": [[141.34, 43.06], [141.341, 43.06]],
            }
        ]
        official = [
            {
                "jartic_id": "jartic:1:0",
                "speed_kmh": 50,
                "path": [[141.3405, 43.0595], [141.3405, 43.0605]],
            }
        ]
        matches = match_jartic_to_segments(segments, official, [], self.bbox)
        self.assertNotIn("osm:1:1:2", matches)

    def test_area_match(self) -> None:
        segments = [
            {
                "segment_id": "osm:1:1:2",
                "path": [[141.3402, 43.0602], [141.3408, 43.0608]],
            }
        ]
        areas = [
            {
                "jartic_id": "jartic:area:0",
                "speed_kmh": 30,
                "path": [
                    [141.34, 43.06],
                    [141.341, 43.06],
                    [141.341, 43.061],
                    [141.34, 43.061],
                ],
            }
        ]
        matches = match_jartic_to_segments(segments, [], areas, self.bbox)
        self.assertEqual("area", matches["osm:1:1:2"]["match_kind"])
        self.assertEqual(30, matches["osm:1:1:2"]["speed_kmh"])


if __name__ == "__main__":
    unittest.main()
