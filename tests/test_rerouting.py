"""Dynamic rerouting must be a genuine recalculation, not a scripted switch."""

import pytest

from backend.errors import EngineError, ErrorCode
from backend.models.emergency import Emergency


@pytest.fixture
def dispatched(engine, icu_emergency):
    """Analyze + confirm the best route, then hand back the context."""
    analysis = engine.analyze(icu_emergency)
    return analysis, analysis["recommended_route"]


def test_reroute_recalculates_after_an_accident(engine, icu_emergency, graph, dispatched):
    _, route = dispatched
    assert route["edges"] == ["AB", "BD"]

    engine.graph.set_traffic("AB", "high")
    from backend.models.incident import Incident

    graph.set_incident("AB", Incident(type="accident", severity="major"))

    result = engine.reroute(
        icu_emergency,
        current_node="A",
        current_route=route,
        trigger={"type": "ACCIDENT", "road_id": "AB", "road_name": "AB Expressway", "severity": "major"},
    )

    assert result["rerouted"] is True
    assert "AB" not in result["new_route"]["edges"]
    assert result["new_eta_minutes"] < result["old_eta_minutes"]
    assert "accident" in result["reasons"]["why_reroute"].lower()


def test_a_closed_road_makes_the_old_route_infeasible(engine, icu_emergency, graph, dispatched):
    _, route = dispatched
    graph.set_status("AB", "closed")

    result = engine.reroute(icu_emergency, current_node="A", current_route=route)

    assert result["old_route"]["feasible"] is False
    assert result["new_route"]["edges"] == ["AC", "CD"]
    assert "AB" not in result["new_route"]["edges"]


def test_reroute_compares_only_the_remaining_leg(engine, icu_emergency, dispatched):
    """Once the ambulance has moved, the old ETA is what is left, not the whole trip."""
    _, route = dispatched
    result = engine.reroute(icu_emergency, current_node="B", current_route=route)
    assert result["old_route"]["nodes"] == ["B", "D"]
    assert result["old_route"]["edges"] == ["BD"]


def test_reroute_keeps_the_route_when_nothing_actually_improved(engine, icu_emergency, dispatched):
    _, route = dispatched
    result = engine.reroute(icu_emergency, current_node="A", current_route=route)
    assert result["rerouted"] is False
    assert "still the best available option" in result["reasons"]["why_reroute"]


def test_reroute_changes_destination_when_the_hospital_goes_full(
    engine, icu_emergency, hospitals, dispatched
):
    """A hospital-capacity event can change *where* the ambulance is going."""
    _, route = dispatched
    assert route["hospital_id"] == "HA"

    # Only HA has ICU+trauma, so once it closes there is no destination at all.
    hospitals["HA"].accepting = False
    with pytest.raises(EngineError) as exc:
        engine.reroute(icu_emergency, current_node="A", current_route=route)
    assert exc.value.code == ErrorCode.NO_ELIGIBLE_HOSPITAL

    # With a laxer requirement, the engine re-points to the other hospital
    # instead of inventing capacity at the closed one.
    cardiac = Emergency.from_dict(
        {"origin_node": "A", "priority": 8, "requirements": ["cardiac"]}
    )
    result = engine.reroute(cardiac, current_node="A", current_route=route)
    assert result["new_route"]["hospital_id"] == "HB"
    assert result["destination_changed"] is True


def test_reroute_fails_explicitly_when_no_route_survives(engine, icu_emergency, graph, dispatched):
    _, route = dispatched
    graph.set_status("AB", "closed")
    graph.set_status("AC", "closed")
    with pytest.raises(EngineError) as exc:
        engine.reroute(icu_emergency, current_node="A", current_route=route)
    assert exc.value.code == ErrorCode.NO_FEASIBLE_ROUTE


def test_reroute_follows_the_graph_not_a_script(engine, icu_emergency, graph):
    """Same trigger, different world state => different route.

    A hardcoded 'if accident then take route 2' would return the same answer
    every time. The engine must re-plan around whatever is actually blocked.
    """
    from backend.models.incident import Incident

    route = engine.analyze(icu_emergency)["recommended_route"]
    assert route["edges"] == ["AB", "BD"]

    graph.set_incident("AB", Incident(type="accident", severity="major"))
    detour = engine.reroute(icu_emergency, current_node="A", current_route=route)
    assert detour["new_route"]["edges"] == ["AC", "CD"]

    # Block the detour as well: the engine re-plans again rather than
    # re-serving a memorised answer, falling back to the only road left open
    # even though it carries the accident.
    graph.set_status("CD", "closed")
    fallback = engine.reroute(icu_emergency, current_node="A", current_route=route)
    assert fallback["new_route"]["edges"] == ["AB", "BD"]
    assert fallback["new_route"]["incident_impact"], "the fallback honestly reports the accident"

    # With every road out of A closed there is no answer to give at all.
    graph.set_status("AB", "closed")
    graph.set_status("AC", "closed")
    with pytest.raises(EngineError) as exc:
        engine.reroute(icu_emergency, current_node="A", current_route=route)
    assert exc.value.code == ErrorCode.NO_FEASIBLE_ROUTE


def test_incident_severity_scales_the_measured_delay(engine, icu_emergency, graph):
    """The penalty is a real, magnitude-dependent delay, not a flag."""
    from backend.models.incident import Incident

    route = engine.analyze(icu_emergency)["recommended_route"]
    etas = []
    for severity in ("minor", "moderate", "major"):
        graph.set_incident("AB", Incident(type="accident", severity=severity))
        result = engine.reroute(icu_emergency, current_node="A", current_route=route)
        etas.append(result["old_route"]["eta_minutes"])
    assert etas == sorted(etas)
    assert etas[0] < etas[-1]


def test_reroute_output_carries_the_full_decision_record(engine, icu_emergency, graph, dispatched):
    _, route = dispatched
    graph.set_status("AB", "closed")
    result = engine.reroute(icu_emergency, current_node="A", current_route=route)

    for key in ("old_route", "new_route", "new_eta_minutes", "alternatives",
                "changed_conditions", "reasons", "hospital"):
        assert key in result
    assert "score_breakdown" in result["new_route"]
    assert result["changed_conditions"]["closed_roads"] == ["AB"]


def test_reroute_from_an_unknown_node_is_rejected(engine, icu_emergency, dispatched):
    _, route = dispatched
    with pytest.raises(EngineError) as exc:
        engine.reroute(icu_emergency, current_node="ZZ", current_route=route)
    assert exc.value.code == ErrorCode.UNKNOWN_NODE
