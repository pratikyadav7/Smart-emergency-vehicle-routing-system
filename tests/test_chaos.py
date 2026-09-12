"""Chaos Mode mutates the world; it never tells the engine what to choose."""

import pytest

from backend.errors import EngineError, ErrorCode
from backend.models.incident import ChaosEvent
from backend.models.road import RoadStatus
from backend.routing.algorithms import a_star
from backend.simulation.chaos import ChaosController


@pytest.fixture
def chaos(graph, hospitals):
    return ChaosController(graph, hospitals)


def test_accident_marks_an_incident_and_adds_real_delay(chaos, graph):
    before = graph.travel_time_min(graph.road("AB"))
    summary = chaos.inject({"type": "ACCIDENT", "road_id": "AB", "severity": "major"})

    road = graph.road("AB")
    assert road.has_incident
    assert road.incident.type == "accident"
    assert road.traffic == "high"
    assert graph.travel_time_min(road) > before
    assert summary["added_delay_minutes"] == 15.0
    assert graph.active_incidents()[0]["road_id"] == "AB"


def test_road_closure_makes_the_road_infeasible(chaos, graph):
    chaos.inject({"type": "ROAD_CLOSURE", "road_id": "AB"})
    assert graph.road("AB").status == RoadStatus.CLOSED
    assert graph.closed_roads() == ["AB"]
    assert "AB" not in a_star(graph, "A", "D").road_ids


def test_traffic_spike_increases_eta(chaos, graph):
    before = graph.travel_time_min(graph.road("AB"))
    summary = chaos.inject({"type": "TRAFFIC_SPIKE", "road_id": "AB"})
    assert graph.road("AB").traffic == "high"
    assert graph.travel_time_min(graph.road("AB")) > before
    assert summary["traffic"] == {"before": "low", "after": "high"}


def test_hospital_capacity_event_changes_eligibility(chaos, hospitals, icu_emergency):
    from backend.routing.hospitals import evaluate_eligibility

    assert "HA" in [h.id for h in evaluate_eligibility(hospitals.values(), icu_emergency).eligible]
    chaos.inject({"type": "HOSPITAL_CAPACITY", "hospital_id": "HA"})
    assert hospitals["HA"].emergency_beds == 0
    assert hospitals["HA"].accepting is False
    assert evaluate_eligibility(hospitals.values(), icu_emergency).eligible == []


def test_hospital_capacity_event_can_set_an_explicit_bed_count(chaos, hospitals):
    chaos.inject({"type": "HOSPITAL_CAPACITY", "hospital_id": "HA", "emergency_beds": 2})
    assert hospitals["HA"].emergency_beds == 2
    assert hospitals["HA"].accepting is True


def test_chaos_is_deterministic_and_replayable(graph, hospitals):
    from backend.routing.graph import RoadGraph
    from tests.conftest import TEST_GRAPH

    events = [{"type": "ACCIDENT", "road_id": "AB", "severity": "moderate"},
              {"type": "TRAFFIC_SPIKE", "road_id": "AC"}]
    results = []
    for _ in range(3):
        fresh = RoadGraph.from_dict(TEST_GRAPH)
        controller = ChaosController(fresh, hospitals)
        for event in events:
            controller.inject(event)
        results.append(a_star(fresh, "A", "D").road_ids)
    assert len({tuple(r) for r in results}) == 1


@pytest.mark.parametrize("payload,expected", [
    ({"type": "METEOR", "road_id": "AB"}, ErrorCode.INVALID_CHAOS_EVENT),
    ({"type": "ACCIDENT"}, ErrorCode.INVALID_CHAOS_EVENT),
    ({"type": "HOSPITAL_CAPACITY"}, ErrorCode.INVALID_CHAOS_EVENT),
    ({"type": "ACCIDENT", "road_id": "AB", "severity": "apocalyptic"}, ErrorCode.INVALID_CHAOS_EVENT),
    ({"type": "ACCIDENT", "road_id": "NOPE"}, ErrorCode.INVALID_CHAOS_EVENT),
    ({"type": "HOSPITAL_CAPACITY", "hospital_id": "HZ"}, ErrorCode.INVALID_CHAOS_EVENT),
    ("not-a-dict", ErrorCode.INVALID_CHAOS_EVENT),
])
def test_malformed_chaos_events_are_rejected(chaos, payload, expected):
    with pytest.raises(EngineError) as exc:
        chaos.inject(payload)
    assert exc.value.code == expected


def test_chaos_event_accepts_the_legacy_edge_id_field():
    event = ChaosEvent.from_dict({"type": "accident", "edge_id": "AB"})
    assert event.road_id == "AB"
    assert event.type == "ACCIDENT"
