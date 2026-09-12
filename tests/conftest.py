"""Shared fixtures. A tiny hand-built graph keeps unit tests independent of
the demo data file, so tuning the Vellore scenario cannot silently break the
algorithm tests."""

import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.models.emergency import Emergency  # noqa: E402
from backend.models.hospital import Hospital  # noqa: E402
from backend.routing.engine import RoutingEngine  # noqa: E402
from backend.routing.graph import RoadGraph  # noqa: E402
from backend.session import DispatchSession  # noqa: E402

#: A deliberately small test city.
#:
#:      A --fast/unsafe-- B --short-- D(hospital HA)
#:      A --slow/safe---- C --------- D
#:      A ------------------------ E(hospital HB, no ICU)
TEST_GRAPH = {
    "city": "Testville",
    "nodes": [
        {"id": "A", "name": "Alpha", "lat": 12.9700, "lon": 79.1000},
        {"id": "B", "name": "Bravo", "lat": 12.9700, "lon": 79.1200},
        {"id": "C", "name": "Charlie", "lat": 12.9600, "lon": 79.1100},
        {"id": "D", "name": "Delta", "lat": 12.9700, "lon": 79.1400},
        {"id": "E", "name": "Echo", "lat": 12.9500, "lon": 79.1000},
    ],
    "edges": [
        {"id": "AB", "from": "A", "to": "B", "name": "AB Expressway",
         "speed_kmph": 60, "capacity": "high", "traffic": "low", "safety": 55, "status": "open"},
        {"id": "BD", "from": "B", "to": "D", "name": "BD Road",
         "speed_kmph": 60, "capacity": "high", "traffic": "low", "safety": 60, "status": "open"},
        {"id": "AC", "from": "A", "to": "C", "name": "AC Lane",
         "speed_kmph": 30, "capacity": "medium", "traffic": "low", "safety": 95, "status": "open"},
        {"id": "CD", "from": "C", "to": "D", "name": "CD Lane",
         "speed_kmph": 30, "capacity": "medium", "traffic": "low", "safety": 95, "status": "open"},
        {"id": "AE", "from": "A", "to": "E", "name": "AE Road",
         "speed_kmph": 40, "capacity": "medium", "traffic": "low", "safety": 80, "status": "open"},
    ],
}

TEST_HOSPITALS = [
    {"id": "HA", "name": "Alpha General", "node": "D", "emergency_beds": 6,
     "icu_available": True, "trauma_available": True, "cardiac_available": True,
     "accepting": True},
    {"id": "HB", "name": "Bravo Clinic", "node": "E", "emergency_beds": 4,
     "icu_available": False, "trauma_available": False, "cardiac_available": True,
     "accepting": True},
]


@pytest.fixture
def graph() -> RoadGraph:
    return RoadGraph.from_dict(TEST_GRAPH)


@pytest.fixture
def hospitals():
    return {h["id"]: Hospital.from_dict(h) for h in TEST_HOSPITALS}


@pytest.fixture
def engine(graph, hospitals) -> RoutingEngine:
    return RoutingEngine(graph=graph, hospitals=hospitals)


@pytest.fixture
def icu_emergency() -> Emergency:
    return Emergency.from_dict(
        {"id": "T001", "origin_node": "A", "priority": 10, "requirements": ["icu", "trauma"]}
    )


@pytest.fixture
def demo_session() -> DispatchSession:
    """A session over the real Vellore demo data."""
    return DispatchSession()
