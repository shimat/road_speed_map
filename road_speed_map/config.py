from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MapPreset:
    # south, west, north, east (Overpass bbox order)
    bbox: tuple[float, float, float, float]
    zoom: float
    note: str = ""
    prepared_dataset: str | None = None

    @property
    def center(self) -> tuple[float, float]:
        south, west, north, east = self.bbox
        return (south + north) / 2, (west + east) / 2


MAP_PRESETS = {
    "札幌市周辺": MapPreset(
        (42.74, 140.84, 43.33, 141.82),
        8.5,
        prepared_dataset="data/processed/central-hokkaido-roads.parquet",
    ),
    "旭川市周辺": MapPreset(
        (43.50, 141.95, 44.05, 142.85),
        8.8,
        "旭川市と近隣市町の市街地を覆います。",
        "data/processed/asahikawa-roads.parquet",
    ),
    "函館市周辺": MapPreset(
        (41.60, 140.50, 42.05, 141.15),
        9.0,
        "函館市、北斗市、七飯町とその周辺を覆います。",
        "data/processed/hakodate-roads.parquet",
    ),
}

SPEED_COLORS: dict[int | str, list[int]] = {
    20: [101, 163, 13, 235],
    30: [25, 118, 210, 235],
    40: [0, 137, 123, 235],
    50: [249, 168, 37, 235],
    60: [229, 57, 53, 235],
    70: [219, 39, 119, 235],
    80: [219, 39, 119, 235],
    90: [219, 39, 119, 235],
    100: [126, 34, 206, 235],
    110: [28, 28, 28, 235],
    120: [28, 28, 28, 235],
    "unknown": [130, 130, 130, 180],
}

SPEED_LEGEND: tuple[tuple[str, int], ...] = (
    ("20", 20),
    ("30", 30),
    ("40", 40),
    ("50", 50),
    ("60", 60),
    ("70–90", 70),
    ("100", 100),
    ("110以上", 110),
)
