"""The score must be complete, deterministic, weight-driven and explainable."""

import pytest

from backend import config
from backend.models.emergency import Emergency
from backend.models.incident import Incident
from backend.routing.algorithms import a_star
from backend.routing.scoring import (
    COMPONENT_KEYS,
    compute_route_metrics,
    score_candidate,
    travel_time_score,
)


def build(graph, hospitals, emergency, destination="D"):
    path = a_star(graph, emergency.origin_node, destination)
    metrics = compute_route_metrics(graph, path)
    hospital = next(h for h in hospitals.values() if h.node == destination)
    return path, metrics, score_candidate(hospital, metrics, emergency)


def test_every_component_is_present(graph, hospitals, icu_emergency):
    _, _, breakdown = build(graph, hospitals, icu_emergency)
    assert set(breakdown.components) == set(COMPONENT_KEYS)
    assert set(breakdown.weights) == set(COMPONENT_KEYS)
    assert set(breakdown.contributions) == set(COMPONENT_KEYS)


def test_total_equals_the_sum_of_its_contributions(graph, hospitals, icu_emergency):
    _, _, breakdown = build(graph, hospitals, icu_emergency)
    assert breakdown.total == pytest.approx(sum(breakdown.contributions.values()))
    for key in COMPONENT_KEYS:
        assert breakdown.contributions[key] == pytest.approx(
            breakdown.components[key] * breakdown.weights[key]
        )


def test_total_is_deterministic(graph, hospitals, icu_emergency):
    totals = {build(graph, hospitals, icu_emergency)[2].total for _ in range(5)}
    assert len(totals) == 1


def test_score_stays_within_zero_and_one_hundred(graph, hospitals, icu_emergency):
    _, _, breakdown = build(graph, hospitals, icu_emergency)
    assert 0.0 <= breakdown.total <= 100.0


def test_priority_selects_a_different_weight_profile():
    assert config.weight_profile_name(10) == "critical"
    assert config.weight_profile_name(5) == "urgent"
    assert config.weight_profile_name(1) == "routine"
    assert config.weights_for_priority(10)["travel_time"] > config.weights_for_priority(1)["travel_time"]
    assert config.weights_for_priority(1)["safety"] > config.weights_for_priority(10)["safety"]


def test_changing_weights_changes_the_ranking(graph, hospitals):
    """The fast-but-unsafe route wins on speed; a safety-heavy profile flips it."""
    fast = a_star(graph, "A", "D")  # A-B-D expressway, safety 55-60
    safe_nodes = ["A", "C", "D"]
    safe_roads = ["AC", "CD"]
    from backend.routing.algorithms import Path

    safe = Path(
        nodes=safe_nodes,
        road_ids=safe_roads,
        distance_km=sum(graph.road(r).distance_km for r in safe_roads),
        travel_time_min=sum(graph.travel_time_min(graph.road(r)) for r in safe_roads),
    )
    hospital = hospitals["HA"]
    critical = Emergency.from_dict({"origin_node": "A", "priority": 10, "requirements": ["icu"]})
    routine = Emergency.from_dict({"origin_node": "A", "priority": 1, "requirements": ["icu"]})

    fast_metrics = compute_route_metrics(graph, fast)
    safe_metrics = compute_route_metrics(graph, safe)

    speed_profile = score_candidate(hospital, fast_metrics, critical, {"travel_time": 1.0})
    safety_profile = score_candidate(hospital, safe_metrics, critical, {"travel_time": 1.0})
    assert speed_profile.total > safety_profile.total

    speed_on_safety = score_candidate(hospital, fast_metrics, routine, {"safety": 1.0})
    safety_on_safety = score_candidate(hospital, safe_metrics, routine, {"safety": 1.0})
    assert safety_on_safety.total > speed_on_safety.total


def test_a_safer_route_can_beat_a_faster_dangerous_one(graph, hospitals):
    """Multi-factor selection, not shortest-path: proven on the real profiles."""
    from backend.routing.algorithms import Path

    fast = a_star(graph, "A", "D")
    safe_roads = ["AC", "CD"]
    safe = Path(
        nodes=["A", "C", "D"],
        road_ids=safe_roads,
        distance_km=sum(graph.road(r).distance_km for r in safe_roads),
        travel_time_min=sum(graph.travel_time_min(graph.road(r)) for r in safe_roads),
    )
    assert safe.travel_time_min > fast.travel_time_min  # genuinely slower

    routine = Emergency.from_dict({"origin_node": "A", "priority": 1, "requirements": ["icu"]})
    hospital = hospitals["HA"]
    fast_score = score_candidate(hospital, compute_route_metrics(graph, fast), routine).total
    safe_score = score_candidate(hospital, compute_route_metrics(graph, safe), routine).total
    assert safe_score > fast_score


def test_incident_penalty_lowers_the_score_and_the_ranking(graph, hospitals, icu_emergency):
    _, _, clean = build(graph, hospitals, icu_emergency)
    graph.set_incident("AB", Incident(type="accident", severity="major"))
    path = graph and a_star(graph, "A", "D")
    metrics = compute_route_metrics(graph, path)
    assert metrics.eta_min >= 0

    # Re-score the *same* road set now carrying the incident.
    from backend.routing.algorithms import Path

    affected = Path(
        nodes=["A", "B", "D"],
        road_ids=["AB", "BD"],
        distance_km=sum(graph.road(r).distance_km for r in ["AB", "BD"]),
        travel_time_min=sum(graph.travel_time_min(graph.road(r)) for r in ["AB", "BD"]),
    )
    affected_metrics = compute_route_metrics(graph, affected)
    dirty = score_candidate(hospitals["HA"], affected_metrics, icu_emergency)

    assert affected_metrics.has_incident
    assert affected_metrics.incident_delay_min == pytest.approx(15.0)
    assert dirty.components["incident_penalty"] < clean.components["incident_penalty"]
    assert dirty.total < clean.total


def test_travel_time_score_is_clamped():
    assert travel_time_score(0.0) == 100.0
    assert travel_time_score(config.ETA_REFERENCE_MIN) == 0.0
    assert travel_time_score(config.ETA_REFERENCE_MIN * 5) == 0.0


def test_weight_profiles_sum_to_one():
    for name, profile in config.PRIORITY_WEIGHT_PROFILES.items():
        assert sum(profile.values()) == pytest.approx(1.0), name
        assert set(profile) == set(COMPONENT_KEYS), name


def test_traffic_metrics_are_distance_weighted(graph, hospitals, icu_emergency):
    path = a_star(graph, "A", "D")
    baseline = compute_route_metrics(graph, path)
    graph.set_traffic("AB", "high")
    worse = compute_route_metrics(graph, path)
    assert worse.traffic_score < baseline.traffic_score
    assert worse.dominant_traffic == "high"
