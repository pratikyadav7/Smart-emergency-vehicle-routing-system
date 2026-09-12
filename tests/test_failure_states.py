"""Every failure is explicit and machine-readable. Nothing is ever faked."""

import json

import pytest

from backend.errors import EngineError, ErrorCode
from backend.history import EventType
from backend.lambda_handlers.analyze.handler import handler as analyze_handler
from backend.lambda_handlers.reroute.handler import handler as reroute_handler
from backend.models.emergency import Emergency


def test_missing_origin_is_rejected():
    with pytest.raises(EngineError) as exc:
        Emergency.from_dict({"priority": 5, "requirements": ["icu"]})
    assert exc.value.code == ErrorCode.MISSING_ORIGIN


@pytest.mark.parametrize("payload", [
    {"origin_node": "A", "priority": 0},
    {"origin_node": "A", "priority": 11},
    {"origin_node": "A", "priority": "urgent"},
    {"origin_node": "A", "requirements": "not-a-list-or-string-we-know"},
])
def test_invalid_emergency_payloads_are_rejected(payload):
    with pytest.raises(EngineError):
        Emergency.from_dict(payload)


def test_unknown_origin_node_is_rejected(engine):
    emergency = Emergency.from_dict({"origin_node": "ZZ", "priority": 5, "requirements": ["icu"]})
    with pytest.raises(EngineError) as exc:
        engine.analyze(emergency)
    assert exc.value.code == ErrorCode.UNKNOWN_NODE


def test_unknown_preferred_hospital_is_rejected(engine):
    emergency = Emergency.from_dict({
        "origin_node": "A", "priority": 5, "requirements": ["icu"],
        "preferred_hospital_id": "H999",
    })
    with pytest.raises(EngineError) as exc:
        engine.analyze(emergency)
    assert exc.value.code == ErrorCode.UNKNOWN_HOSPITAL


def test_no_eligible_hospital_is_an_explicit_state(engine, hospitals):
    for hospital in hospitals.values():
        hospital.accepting = False
    emergency = Emergency.from_dict({"origin_node": "A", "priority": 9, "requirements": ["icu"]})
    with pytest.raises(EngineError) as exc:
        engine.analyze(emergency)
    assert exc.value.code == ErrorCode.NO_ELIGIBLE_HOSPITAL
    assert exc.value.details["rejected"], "the dispatcher is told why each hospital failed"


def test_all_roads_closed_is_an_explicit_state(engine, graph, icu_emergency):
    for road_id in list(graph.roads):
        graph.set_status(road_id, "closed")
    with pytest.raises(EngineError) as exc:
        engine.analyze(icu_emergency)
    assert exc.value.code == ErrorCode.NO_FEASIBLE_ROUTE


def test_unreachable_hospital_is_reported_not_invented(graph, hospitals, icu_emergency):
    """An eligible hospital with no road to it must not be recommended."""
    from backend.models.hospital import Hospital
    from backend.routing.engine import RoutingEngine

    graph.nodes["ISLAND"] = graph.nodes["D"].__class__(
        id="ISLAND", name="Island", lat=13.5, lon=79.9
    )
    graph._adjacency["ISLAND"] = []
    hospitals["HZ"] = Hospital.from_dict({
        "id": "HZ", "name": "Island Hospital", "node": "ISLAND", "emergency_beds": 9,
        "icu_available": True, "trauma_available": True, "cardiac_available": True,
        "accepting": True,
    })
    engine = RoutingEngine(graph=graph, hospitals=hospitals)
    result = engine.analyze(icu_emergency)
    assert result["hospital"]["id"] != "HZ"
    assert all(r["hospital_id"] != "HZ" for r in result["routes"])


def test_confirming_a_dispatch_before_analyzing_is_rejected(demo_session):
    with pytest.raises(EngineError) as exc:
        demo_session.confirm_dispatch()
    assert exc.value.code == ErrorCode.INVALID_REQUEST


def test_confirming_a_route_that_was_not_offered_is_rejected(demo_session):
    demo_session.create_emergency({"origin_node": "N2", "priority": 9, "requirements": ["icu"]})
    demo_session.analyze()
    with pytest.raises(EngineError) as exc:
        demo_session.confirm_dispatch(route_id="R-NOPE-1")
    assert exc.value.code == ErrorCode.INVALID_REQUEST


def test_reroute_before_analyze_is_rejected(demo_session):
    with pytest.raises(EngineError) as exc:
        demo_session.reroute()
    assert exc.value.code == ErrorCode.INVALID_EMERGENCY


def test_hospital_becoming_unavailable_mid_simulation_is_handled(demo_session):
    demo_session.create_emergency({
        "origin_node": "N2", "priority": 10, "requirements": ["icu", "trauma"],
    })
    demo_session.analyze()
    demo_session.confirm_dispatch()
    destination = demo_session.active_route["hospital_id"]

    demo_session.inject_chaos({"type": "HOSPITAL_CAPACITY", "hospital_id": destination})
    result = demo_session.reroute()

    assert result["new_route"]["hospital_id"] != destination
    assert result["destination_changed"] is True


# --- Lambda-level error envelopes -----------------------------------------

@pytest.mark.parametrize("body,code,status", [
    ({"emergency": {"priority": 5}}, ErrorCode.MISSING_ORIGIN, 400),
    ({"emergency": {"origin_node": "N1", "requirements": ["xray"]}},
     ErrorCode.UNSUPPORTED_REQUIREMENT, 400),
    ({"emergency": {"origin_node": "NOWHERE", "priority": 5}}, ErrorCode.UNKNOWN_NODE, 400),
])
def test_analyze_handler_returns_error_envelopes(body, code, status):
    response = analyze_handler({"body": json.dumps(body)})
    assert response["statusCode"] == status
    payload = json.loads(response["body"])
    assert payload["status"] == "error"
    assert payload["error"]["code"] == code


def test_analyze_handler_reports_no_feasible_answer_as_409():
    body = {
        "emergency": {"origin_node": "N1", "priority": 10, "requirements": ["icu", "trauma"]},
        "environment": {"chaos_events": [
            {"type": "HOSPITAL_CAPACITY", "hospital_id": "H1"},
            {"type": "HOSPITAL_CAPACITY", "hospital_id": "H2"},
        ]},
    }
    response = analyze_handler({"body": json.dumps(body)})
    assert response["statusCode"] == 409
    assert json.loads(response["body"])["error"]["code"] == ErrorCode.NO_ELIGIBLE_HOSPITAL


def test_malformed_json_body_is_rejected():
    response = analyze_handler({"body": "{not json"})
    assert response["statusCode"] == 400
    assert json.loads(response["body"])["error"]["code"] == ErrorCode.INVALID_REQUEST


def test_reroute_handler_requires_a_current_node():
    body = {"emergency": {"origin_node": "N1", "priority": 8, "requirements": ["icu"]}}
    response = reroute_handler({"body": json.dumps(body)})
    assert response["statusCode"] == 400
    assert json.loads(response["body"])["error"]["code"] == ErrorCode.INVALID_REQUEST


def test_malformed_chaos_event_through_the_handler_is_a_400():
    body = {
        "emergency": {"origin_node": "N1", "priority": 8, "requirements": ["icu"]},
        "environment": {"chaos_events": [{"type": "TSUNAMI"}]},
    }
    response = analyze_handler({"body": json.dumps(body)})
    assert response["statusCode"] == 400
    assert json.loads(response["body"])["error"]["code"] == ErrorCode.INVALID_CHAOS_EVENT


def test_dead_ends_are_recorded_in_the_history(demo_session):
    """A refusal is a decision the audit trail must show."""
    demo_session.create_emergency({
        "origin_node": "N2", "priority": 10, "requirements": ["icu", "trauma"],
    })
    for hospital_id in ("H1", "H2", "H3"):
        demo_session.inject_chaos({"type": "HOSPITAL_CAPACITY", "hospital_id": hospital_id})

    with pytest.raises(EngineError) as exc:
        demo_session.analyze()
    assert exc.value.code == ErrorCode.NO_ELIGIBLE_HOSPITAL

    events = demo_session.history_events()["events"]
    assert any(e["event_type"] == EventType.NO_FEASIBLE_OPTION for e in events)


def test_failed_reroute_is_recorded_in_the_history(demo_session):
    demo_session.create_emergency({
        "origin_node": "N2", "priority": 10, "requirements": ["icu", "trauma"],
    })
    demo_session.analyze()
    demo_session.confirm_dispatch()
    for road_id in list(demo_session.graph.roads):
        demo_session.inject_chaos({"type": "ROAD_CLOSURE", "road_id": road_id})

    with pytest.raises(EngineError) as exc:
        demo_session.reroute()
    assert exc.value.code == ErrorCode.NO_FEASIBLE_ROUTE

    events = demo_session.history_events()["events"]
    assert any(e["event_type"] == EventType.REROUTE_FAILED for e in events)
