import unittest

from road_speed_map.speeds import (
    apply_human_knowledge,
    apply_structure_observation,
    enrich_segment,
    infer_statutory_speed,
    parse_speed,
    source_data_only,
    speed_color,
)


class SpeedTests(unittest.TestCase):
    def test_high_speed_colors_use_three_distinct_classes(self) -> None:
        self.assertEqual(speed_color(70), speed_color(80))
        self.assertEqual(speed_color(80), speed_color(90))
        self.assertEqual(speed_color(110), speed_color(120))
        self.assertNotEqual(speed_color(70), speed_color(100))
        self.assertNotEqual(speed_color(100), speed_color(110))
        self.assertNotEqual(speed_color(20), speed_color(70))
        self.assertNotEqual(speed_color(20), speed_color(100))
        self.assertNotEqual(speed_color(20), speed_color(110))

    def test_parse_speed_accepts_numeric_osm_values_only(self) -> None:
        self.assertEqual(30, parse_speed("30"))
        self.assertEqual(50, parse_speed("50 km/h"))
        self.assertIsNone(parse_speed("signals"))
        self.assertIsNone(parse_speed("30;50"))

    def test_center_line_heuristic(self) -> None:
        speed, _, confidence = infer_statutory_speed(
            {"highway": "residential", "lanes": "2", "lane_markings": "yes"}
        )
        self.assertEqual(60, speed)
        self.assertEqual("medium", confidence)

    def test_minor_road_without_lane_markings_is_inferred_30(self) -> None:
        speed, _, confidence = infer_statutory_speed(
            {"highway": "residential", "lane_markings": "no"}
        )
        self.assertEqual(30, speed)
        self.assertEqual("medium", confidence)

    def test_residential_road_without_structure_tags_is_low_confidence_30(self) -> None:
        speed, reason, confidence = infer_statutory_speed({"highway": "residential"})
        self.assertEqual(30, speed)
        self.assertIn("未確認", reason)
        self.assertEqual("low", confidence)

    def test_manual_override_has_highest_precedence(self) -> None:
        segment = {
            "segment_id": "osm:1:2:3",
            "tags": {"highway": "residential", "maxspeed": "40"},
        }
        enriched = enrich_segment(
            segment,
            {"speed_kmh": 30, "evidence_type": "現地で標識を確認"},
        )
        self.assertEqual(30, enriched["speed_kmh"])
        self.assertEqual("manual", enriched["basis"])

    def test_jartic_match_precedes_osm_speed(self) -> None:
        segment = {
            "segment_id": "osm:1:2:3",
            "tags": {"highway": "residential", "maxspeed": "40"},
        }
        enriched = enrich_segment(
            segment,
            jartic_match={"speed_kmh": 30, "distance_m": 2.5},
        )
        self.assertEqual(30, enriched["speed_kmh"])
        self.assertEqual("jartic", enriched["basis"])
        self.assertEqual("medium", enriched["confidence"])

    def test_manual_override_precedes_jartic_match(self) -> None:
        segment = {
            "segment_id": "osm:1:2:3",
            "tags": {"highway": "residential", "maxspeed": "40"},
        }
        enriched = enrich_segment(
            segment,
            {"speed_kmh": 20, "evidence_type": "現地で標識を確認"},
            {"speed_kmh": 30, "distance_m": 2.5},
        )
        self.assertEqual(20, enriched["speed_kmh"])
        self.assertEqual("manual", enriched["basis"])

    def test_directional_conflict_is_not_flattened(self) -> None:
        segment = {
            "segment_id": "osm:1:2:3",
            "tags": {
                "highway": "secondary",
                "maxspeed:forward": "50",
                "maxspeed:backward": "40",
            },
        }
        enriched = enrich_segment(segment)
        self.assertIsNone(enriched["speed_kmh"])
        self.assertEqual("unknown", enriched["basis"])

    def test_statutory_inference_can_be_disabled(self) -> None:
        segment = {
            "segment_id": "osm:1:2:3",
            "tags": {"highway": "residential", "lanes": "2"},
        }
        enriched = enrich_segment(segment, infer_statutory=False)
        self.assertIsNone(enriched["speed_kmh"])
        self.assertEqual("unknown", enriched["basis"])

    def test_source_data_only_removes_manual_and_inferred_values(self) -> None:
        manual = enrich_segment(
            {"segment_id": "osm:1:2:3", "tags": {"highway": "residential"}},
            {"speed_kmh": 40, "evidence_type": "現地確認"},
        )
        inferred = enrich_segment(
            {
                "segment_id": "osm:4:5:6",
                "tags": {"highway": "residential", "lanes": "2"},
            }
        )
        source_rows = source_data_only([manual, inferred])
        self.assertTrue(all(row["basis"] == "unknown" for row in source_rows))

    def test_center_line_observation_creates_statutory_60_candidate(self) -> None:
        row = enrich_segment(
            {"segment_id": "osm:1:2:3", "tags": {"highway": "residential"}},
            infer_statutory=False,
        )
        observed = apply_structure_observation(
            row,
            {"observed_feature": "center_line", "sign_status": "not_checked"},
        )
        self.assertEqual(60, observed["speed_kmh"])
        self.assertEqual("human_observation", observed["basis"])
        self.assertEqual("medium", observed["confidence"])
        self.assertIn("未確認", observed["reason"])

    def test_no_center_line_observation_creates_statutory_30_candidate(self) -> None:
        row = enrich_segment(
            {"segment_id": "osm:1:2:3", "tags": {"highway": "residential"}},
            infer_statutory=False,
        )
        observed = apply_structure_observation(
            row,
            {
                "observed_feature": "no_center_line",
                "sign_status": "none_in_selected_range",
            },
        )
        self.assertEqual(30, observed["speed_kmh"])
        self.assertIn("標識なし", observed["reason"])

    def test_designated_speed_precedes_structure_observation(self) -> None:
        row = enrich_segment(
            {"segment_id": "osm:1:2:3", "tags": {"highway": "residential"}},
            jartic_match={"speed_kmh": 40, "distance_m": 1.0},
        )
        result = apply_human_knowledge(
            [row],
            {},
            {
                "osm:1:2:3": {
                    "observed_feature": "center_line",
                    "sign_status": "not_checked",
                }
            },
        )
        self.assertEqual(40, result[0]["speed_kmh"])
        self.assertEqual("jartic", result[0]["basis"])


if __name__ == "__main__":
    unittest.main()
