"""
The mandatory demo scenario, asserted step by step.

This is the scripted sequence the judges see, encoded as a test so it cannot
silently rot: Priority-10 ICU + trauma, preferred hospital unavailable, three
routes, dispatch, green corridor, accident on the active route, genuine
recalculation, reroute confirmation, updated ETA, history events.
"""

import json
import os

import pytest

from backend.history import EventType
from backend.models.simulation_state import AmbulanceStatus, SignalState
from backend.session import DispatchSession

SCENARIO_PATH = os.path.join(
    os.path.dirname(__file__), "..", "data", "scenarios", "mandatory_demo.json"
)


@pytest.fixture
def scenario():
    with open(SCENARIO_PATH, encoding="utf-8") as handle:
        return json.load(handle)


@pytest.fixture
def session(scenario):
    session = DispatchSession()
    for event in scenario["setup_events"]:
        session.inject_chaos(event)
    return session


def test_mandatory_scenario_end_to_end(session, scenario):
    # 1-3. Priority-10 ICU + trauma emergency, preferring H1.
    created = session.create_emergency(scenario["emergency"])
    assert created["emergency"]["priority"] == 10
    assert created["emergency"]["requirements"] == ["icu", "trauma"]
    assert created["emergency"]["preferred_hospital_id"] == "H1"

    # 4-5. H1 is unavailable, so a *different* suitable hospital is selected.
    analysis = session.analyze()
    assert analysis["hospital"]["id"] != "H1", "an unsuitable preferred hospital is not used"
    assert analysis["hospital"]["icu_available"] and analysis["hospital"]["trauma_available"]
    assert analysis["hospital"]["accepting"] is True
    assert analysis["eligibility"]["preferred_hospital_used"] is False
    assert "H1" in [r["hospital_id"] for r in analysis["eligibility"]["rejected_hospitals"]]
    assert analysis["reasons"]["warning"]

    # 6-7. Three feasible route alternatives, each with a score breakdown.
    assert len(analysis["routes"]) == 3
    assert len({tuple(r["edges"]) for r in analysis["routes"]}) == 3
    for route in analysis["routes"]:
        assert route["score_breakdown"]["components"]
        assert route["eta_minutes"] > 0
    assert analysis["reasons"]["why_this_hospital"]
    assert analysis["reasons"]["why_this_route"]
    assert len(analysis["reasons"]["why_not_alternatives"]) == 2

    # 8-10. Dispatcher confirms; ambulance starts; green corridor activates.
    confirmed = session.confirm_dispatch()
    original_route = confirmed["confirmed_route"]
    assert confirmed["ambulance"]["status"] == AmbulanceStatus.EN_ROUTE
    assert confirmed["green_corridor"]["active"] is True
    assert confirmed["green_corridor"]["simulated"] is True
    assert confirmed["green_corridor"]["priority_nodes"] == original_route["nodes"]

    # The ambulance advances junction by junction.
    moved = session.advance(scenario["advance_steps_before_chaos"])
    assert moved["ambulance"]["current_node"] == original_route["nodes"][1]
    signals = {j["node_id"]: j["state"] for j in moved["green_corridor"]["junctions"]}
    assert signals[original_route["nodes"][0]] == SignalState.CLEARED
    assert signals[original_route["nodes"][1]] == SignalState.PRIORITY_GRANTED

    # 11. Chaos Mode: an accident on the road the ambulance is about to use.
    chaos = session.inject_chaos(scenario["chaos_event"])
    assert chaos["affects_active_route"] is True
    assert chaos["reroute_recommended"] is True
    assert session.graph.road(scenario["chaos_event"]["road_id"]).has_incident

    # 12-13. The engine recalculates and a backup route becomes recommended.
    reroute = session.reroute()
    assert reroute["rerouted"] is True
    assert scenario["chaos_event"]["road_id"] not in reroute["new_route"]["edges"]
    assert reroute["new_route"]["nodes"][0] == moved["ambulance"]["current_node"]
    assert reroute["old_eta_minutes"] > reroute["new_eta_minutes"], (
        "the backup route is chosen because it is genuinely better now"
    )
    assert "accident" in reroute["reasons"]["why_reroute"].lower()

    # 14-15. Dispatcher confirms the reroute; an updated ETA comes back.
    reconfirmed = session.confirm_reroute()
    new_route = reconfirmed["confirmed_route"]
    assert new_route["edges"] != original_route["edges"]
    assert reconfirmed["updated_eta_minutes"] == new_route["eta_minutes"]
    assert reconfirmed["ambulance"]["reroute_count"] == 1
    assert reconfirmed["ambulance"]["route"][0] == moved["ambulance"]["current_node"]
    assert reconfirmed["green_corridor"]["priority_nodes"] == new_route["nodes"]

    # The ambulance completes the new route and arrives.
    for _ in range(len(new_route["nodes"])):
        state = session.advance(1)
        if state["ambulance"]["arrived"]:
            break
    assert state["ambulance"]["status"] == AmbulanceStatus.ARRIVED
    assert state["ambulance"]["current_node"] == analysis["hospital"]["node"]
    assert state["green_corridor"]["active"] is False

    # 16. History records every decision, in order, JSON-safe.
    events = session.history_events()["events"]
    types = [e["event_type"] for e in events]
    for expected in (
        EventType.CHAOS_INJECTED,
        EventType.EMERGENCY_CREATED,
        EventType.HOSPITAL_REJECTED,
        EventType.RECOMMENDATION,
        EventType.DISPATCH_CONFIRMED,
        EventType.AMBULANCE_MOVED,
        EventType.CORRIDOR_GRANTED,
        EventType.REROUTE_PROPOSED,
        EventType.REROUTE_CONFIRMED,
        EventType.ARRIVED,
    ):
        assert expected in types, expected
    assert types.index(EventType.EMERGENCY_CREATED) < types.index(EventType.RECOMMENDATION)
    assert types.index(EventType.REROUTE_PROPOSED) < types.index(EventType.REROUTE_CONFIRMED)
    json.dumps(events)


def test_scenario_is_repeatable(scenario):
    """Two independent runs must produce identical decisions."""

    def run():
        session = DispatchSession()
        for event in scenario["setup_events"]:
            session.inject_chaos(event)
        session.create_emergency(scenario["emergency"])
        analysis = session.analyze()
        session.confirm_dispatch()
        session.advance(scenario["advance_steps_before_chaos"])
        session.inject_chaos(scenario["chaos_event"])
        reroute = session.reroute()
        return {
            "hospital": analysis["hospital"]["id"],
            "routes": [(r["route_id"], r["score"]) for r in analysis["routes"]],
            "new_route": reroute["new_route"]["edges"],
            "new_eta": reroute["new_eta_minutes"],
        }

    assert run() == run()


def test_state_endpoint_reflects_the_live_simulation(session, scenario):
    session.create_emergency(scenario["emergency"])
    session.analyze()
    session.confirm_dispatch()
    session.advance(1)

    state = session.state()
    assert state["emergency"]["id"] == scenario["emergency"]["id"]
    assert state["ambulance"]["status"] == AmbulanceStatus.EN_ROUTE
    assert state["green_corridor"]["active"] is True
    assert state["active_route"] is not None
    assert len(state["hospitals"]) == 3
    json.dumps(state)
