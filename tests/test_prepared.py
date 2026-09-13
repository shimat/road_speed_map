import tempfile
import unittest
from pathlib import Path

from road_speed_map.prepared import (
    extract_pbf_roads,
    load_prepared_segments,
    write_segments_parquet,
)


class PreparedDatasetTests(unittest.TestCase):
    def test_parquet_round_trip_preserves_enriched_segment(self) -> None:
        segment = {
            "segment_id": "osm:10:1:2",
            "osm_way_id": 10,
            "from_node": "1",
            "to_node": "2",
            "road_name": "テスト通",
            "road_label": "テスト通（residential）",
            "path": [[141.34, 43.06], [141.341, 43.061]],
            "tags": {"highway": "residential", "maxspeed": "30"},
            "speed_kmh": 30,
            "speed_label": "30 km/h",
            "basis": "osm",
            "basis_label": "OSMのmaxspeed",
            "confidence": "medium",
            "confidence_label": "中",
            "reason": "OSMに数値のmaxspeedあり",
            "color": [25, 118, 210, 235],
        }
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "roads.parquet"
            self.assertEqual(1, write_segments_parquet([segment], destination))
            self.assertEqual(segment, load_prepared_segments(destination)[0])

    def test_extracts_only_drivable_road_inside_bbox(self) -> None:
        osm_xml = """<?xml version="1.0" encoding="UTF-8"?>
<osm version="0.6">
  <node id="1" lat="43.0600" lon="141.3400" />
  <node id="2" lat="43.0610" lon="141.3410" />
  <node id="3" lat="44.0000" lon="142.0000" />
  <node id="4" lat="44.0010" lon="142.0010" />
  <way id="10"><nd ref="1"/><nd ref="2"/><tag k="highway" v="residential"/></way>
  <way id="11"><nd ref="3"/><nd ref="4"/><tag k="highway" v="primary"/></way>
  <way id="12"><nd ref="1"/><nd ref="2"/><tag k="highway" v="footway"/></way>
</osm>"""
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "tiny.osm"
            destination = Path(temporary) / "roads.parquet"
            source.write_text(osm_xml, encoding="utf-8")
            count = extract_pbf_roads(
                source,
                destination,
                (43.05, 141.33, 43.07, 141.35),
            )
            rows = load_prepared_segments(destination)
        self.assertEqual(1, count)
        self.assertEqual(10, rows[0]["osm_way_id"])


if __name__ == "__main__":
    unittest.main()
