import unittest

from road_speed_map.jartic import intersects_bbox, parse_coordinate_parts


class JarticTests(unittest.TestCase):
    def test_coordinate_parts(self) -> None:
        value = "141.34 43.06;141.35 43.07/141.36 43.08;141.37 43.09"
        self.assertEqual(
            [
                [[141.34, 43.06], [141.35, 43.07]],
                [[141.36, 43.08], [141.37, 43.09]],
            ],
            parse_coordinate_parts(value),
        )

    def test_bbox_intersection(self) -> None:
        bbox = (43.05, 141.33, 43.08, 141.38)
        self.assertTrue(intersects_bbox([[141.34, 43.06], [141.35, 43.07]], bbox))
        self.assertFalse(intersects_bbox([[140.0, 42.0], [140.1, 42.1]], bbox))


if __name__ == "__main__":
    unittest.main()
