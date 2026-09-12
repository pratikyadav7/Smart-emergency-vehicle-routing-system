"""The engine's output must be JSON-serialisable and contract-shaped."""

import json

import pytest

from backend.lambda_handlers.analyze.handler import handler as analyze_handler
from backend.lambda_handlers.reroute.handler import handler as reroute_handler
from backend.routing.scoring import COMPONENT_KEYS

EMERGENCY = {
    "id": "E001",
    "origin_node": "N2",
    "priority": 10,
    "requirements": ["icu", "trauma"],
    "preferred_hospital_id": "H1",
    "ambulance_id": "A01",
}


def analyze(body):
    response = analyze_handler({"body": json.dumps(body)})
    assert response["statusCode"] == 200, response["body"]
    return json.loads(response["body"])


def test_analyze_returns_the_documented_envelope():
    payload = analyze({"emergency": EMERGENCY})
    for key in ("status", "emergency", "hospital", "recommended_route",
                "alternatives", "routes", "eligibility", "reasons", "environment"):
        assert key in payload
    assert payload["status"] == "ok"


def test_every_route_carries_metrics_and_a_full_breakdown():
    payload = analyze({"emergency": EMERGENCY})
    for route in payload["routes"]:
        for key in ("route_id", "hospital_id", "nodes", "edges", "distance_km",
                    "eta_minutes", "traffic_condition", "safety_score",
                    "capacity_score", "incident_impact", "score",
                    "score_breakdown", "recommended"):
            assert key in route, key
        assert set(route["score_breakdown"]["components"]) == set(COMPONENT_KEYS)
        assert route["score_breakdown"]["total"] == pytest.approx(route["score"])


def test_exactly_one_route_is_flagged_as_recommended():
    payload = analyze({"emergency": EMERGENCY})
    assert sum(1 for r in payload["routes"] if r["recommended"]) == 1
    assert payload["routes"][0]["route_id"] == payload["recommended_route"]["route_id"]


def test_routes_are_ranked_by_score():
    payload = analyze({"emergency": EMERGENCY})
    scores = [r["score"] for r in payload["routes"]]
    assert scores == sorted(scores, reverse=True)


def test_response_is_json_safe_end_to_end():
    response = analyze_handler({"body": json.dumps({"emergency": EMERGENCY})})
    reparsed = json.loads(response["body"])
    json.dumps(reparsed)  # round-trips with no Python-only objects
    assert response["headers"]["Content-Type"] == "application/json"


def test_analyze_accepts_a_direct_invoke_payload():
    response = analyze_handler({"emergency": EMERGENCY})
    assert response["statusCode"] == 200


def test_analyze_is_deterministic_across_calls():
    first = analyze({"emergency": EMERGENCY})
    second = analyze({"emergency": EMERGENCY})
    assert first["recommended_route"]["route_id"] == second["recommended_route"]["route_id"]
    assert first["recommended_route"]["score"] == second["recommended_route"]["score"]


def test_chaos_events_replay_into_a_stateless_analyze_call():
    clean = analyze({"emergency": EMERGENCY})
    disrupted = analyze({
        "emergency": EMERGENCY,
        "environment": {"chaos_events": [{"type": "HOSPITAL_CAPACITY", "hospital_id": "H1"}]},
    })
    assert clean["hospital"]["id"] == "H1"
    assert disrupted["hospital"]["id"] != "H1"
    assert disrupted["reasons"]["warning"], "the dispatcher is told why H1 was not used"


def test_reroute_handler_returns_the_documented_envelope():
    baseline = analyze({"emergency": EMERGENCY})
    route = baseline["recommended_route"]

    response = reroute_handler({"body": json.dumps({
        "emergency": EMERGENCY,
        "ambulance": {"current_node": route["nodes"][1], "ambulance_id": "A01"},
        "current_route": route,
        "environment": {"chaos_events": [
            {"type": "ROAD_CLOSURE", "road_id": route["edges"][1]},
        ]},
        "trigger": {"type": "ROAD_CLOSURE", "road_id": route["edges"][1]},
    })})

    assert response["statusCode"] == 200, response["body"]
    payload = json.loads(response["body"])
    for key in ("rerouted", "old_route", "new_route", "new_eta_minutes",
                "alternatives", "changed_conditions", "reasons"):
        assert key in payload
    assert route["edges"][1] not in payload["new_route"]["edges"]
    json.dumps(payload)


def test_analyze_and_reroute_share_one_scoring_implementation():
    """Same world, same origin => the two endpoints must agree."""
    baseline = analyze({"emergency": EMERGENCY})
    response = reroute_handler({"body": json.dumps({
        "emergency": EMERGENCY,
        "ambulance": {"current_node": EMERGENCY["origin_node"]},
    })})
    payload = json.loads(response["body"])
    assert payload["new_route"]["route_id"] == baseline["recommended_route"]["route_id"]
    assert payload["new_route"]["score"] == baseline["recommended_route"]["score"]


def test_history_events_are_json_safe_and_typed():
    payload = analyze({"emergency": EMERGENCY})
    assert payload["history"], "analyze produces history-compatible events"
    for event in payload["history"]:
        assert {"id", "timestamp", "event_type", "message"} <= set(event)
        json.dumps(event)
