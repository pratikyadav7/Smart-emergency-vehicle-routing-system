"""Ambulance movement and the simulated green corridor."""

import pytest

from backend.errors import EngineError, ErrorCode
from backend.models.simulation_state import AmbulanceStatus, SignalState
from backend.simulation.ambulance import AmbulanceSimulator
from backend.simulation.corridor import GreenCorridorController


@pytest.fixture
def sim(graph):
    return AmbulanceSimulator(graph)


def test_ambulance_progresses_node_by_node(sim):
    sim.dispatch("A01", ["A", "B", "D"])
    assert sim.state.current_node == "A"
    assert sim.state.next_node == "B"
    assert sim.state.status == AmbulanceStatus.EN_ROUTE

    sim.advance()
    assert sim.state.current_node == "B"
    assert sim.state.current_index == 1

    sim.advance()
    assert sim.state.current_node == "D"
    assert sim.state.has_arrived
    assert sim.state.status == AmbulanceStatus.ARRIVED


def test_remaining_eta_decreases_as_the_ambulance_moves(sim):
    sim.dispatch("A01", ["A", "B", "D"])
    start = sim.state.remaining_eta_min
    sim.advance()
    assert sim.state.remaining_eta_min < start
    sim.advance()
    assert sim.state.remaining_eta_min == pytest.approx(0.0)


def test_elapsed_plus_remaining_equals_total(sim):
    sim.dispatch("A01", ["A", "B", "D"])
    total = sim.state.total_eta_min
    sim.advance()
    assert sim.state.elapsed_min + sim.state.remaining_eta_min == pytest.approx(total)


def test_advancing_past_the_destination_is_a_no_op(sim):
    sim.dispatch("A01", ["A", "B"])
    sim.advance()
    result = sim.advance()
    assert result["moved"] is False
    assert result["arrived"] is True


def test_remaining_eta_reflects_a_mid_transit_traffic_change(sim, graph):
    sim.dispatch("A01", ["A", "B", "D"])
    sim.advance()  # now at B, only B-D left
    before = sim.state.remaining_eta_min
    graph.set_traffic("BD", "high")
    assert sim.remaining_eta() > before


def test_moving_onto_a_closed_road_raises_rather_than_teleporting(sim, graph):
    sim.dispatch("A01", ["A", "B", "D"])
    graph.set_status("AB", "closed")
    with pytest.raises(EngineError) as exc:
        sim.advance()
    assert exc.value.code == ErrorCode.NO_FEASIBLE_ROUTE
    assert sim.state.status == AmbulanceStatus.BLOCKED


def test_advance_before_dispatch_is_an_explicit_error(sim):
    with pytest.raises(EngineError) as exc:
        sim.advance()
    assert exc.value.code == ErrorCode.SIMULATION_NOT_STARTED


def test_reassigned_route_must_start_at_the_current_node(sim):
    sim.dispatch("A01", ["A", "B", "D"])
    sim.advance()
    with pytest.raises(EngineError):
        sim.assign_route(["A", "C", "D"])
    sim.assign_route(["B", "D"])
    assert sim.state.reroute_count == 1
    assert sim.state.route_nodes == ["B", "D"]


def test_dispatch_rejects_unknown_nodes(sim):
    with pytest.raises(EngineError) as exc:
        sim.dispatch("A01", ["A", "ZZ"])
    assert exc.value.code == ErrorCode.UNKNOWN_NODE


def test_green_corridor_grants_priority_along_the_route(graph, sim):
    corridor = GreenCorridorController(graph)
    sim.dispatch("A01", ["A", "B", "D"])
    state = corridor.activate(sim.state.route_nodes)
    assert state.active is True
    assert state.to_dict()["priority_nodes"] == ["A", "B", "D"]
    assert state.to_dict()["simulated"] is True


def test_green_corridor_releases_junctions_already_cleared(graph, sim):
    corridor = GreenCorridorController(graph)
    sim.dispatch("A01", ["A", "B", "D"])
    corridor.activate(sim.state.route_nodes)

    sim.advance()
    state = corridor.sync(sim.state)
    by_node = {j.node_id: j.state for j in state.junctions}
    assert by_node["A"] == SignalState.CLEARED
    assert by_node["B"] == SignalState.PRIORITY_GRANTED
    assert by_node["D"] == SignalState.PRIORITY_GRANTED


def test_green_corridor_deactivates_on_arrival(graph, sim):
    corridor = GreenCorridorController(graph)
    sim.dispatch("A01", ["A", "B"])
    corridor.activate(sim.state.route_nodes)
    sim.advance()
    state = corridor.sync(sim.state)
    assert state.active is False


def test_corridor_never_claims_real_infrastructure_control(graph):
    corridor = GreenCorridorController(graph)
    payload = corridor.activate(["A", "B"]).to_dict()
    assert payload["simulated"] is True
    assert "No real traffic infrastructure" in payload["note"]
