import unittest

from road_speed_map.osm import bbox_tiles, segments_from_overpass


class OsmTests(unittest.TestCase):
    def test_large_bbox_is_tiled(self) -> None:
        tiles = bbox_tiles((43.03, 141.30, 43.10, 141.41))
        self.assertEqual(6, len(tiles))
        self.assertEqual((43.03, 141.30, 43.065, 141.33666666666667), tiles[0])
        self.assertAlmostEqual(43.10, tiles[-1][2])
        self.assertAlmostEqual(141.41, tiles[-1][3])

    def test_sapporo_city_bbox_is_split_into_manageable_tiles(self) -> None:
        tiles = bbox_tiles((42.778, 140.988, 43.192, 141.509))
        self.assertEqual(99, len(tiles))

    def test_way_is_split_into_stable_edge_segments(self) -> None:
        payload = {
            "elements": [
                {
                    "type": "way",
                    "id": 42,
                    "nodes": [100, 200, 300],
                    "tags": {"highway": "residential", "name": "北1条通"},
                    "geometry": [
                        {"lat": 43.0, "lon": 141.0},
                        {"lat": 43.1, "lon": 141.1},
                        {"lat": 43.2, "lon": 141.2},
                    ],
                }
            ]
        }
        segments = segments_from_overpass(payload)
        self.assertEqual(2, len(segments))
        self.assertEqual("osm:42:100:200", segments[0]["segment_id"])
        self.assertEqual([[141.0, 43.0], [141.1, 43.1]], segments[0]["path"])


if __name__ == "__main__":
    unittest.main()
