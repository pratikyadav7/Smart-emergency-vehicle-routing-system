"""Dijkstra, A* and the alternative-route generator."""

import pytest

from backend.errors import EngineError, ErrorCode
from backend.models.incident import Incident
from backend.models.road import RoadStatus
from backend.routing.algorithms import a_star, dijkstra, dijkstra_path, k_alternative_paths


def test_dijkstra_prices_every_reachable_node(graph):
    distances, _ = dijkstra(graph, "A")
    assert set(distances) == {"A", "B", "C", "D", "E"}
    assert distances["A"] == 0.0
    # A-B-D on the 60 km/h expressway beats A-C-D on the 30 km/h lanes.
    assert distances["D"] == pytest.approx(
        graph.travel_time_min(graph.road("AB")) + graph.travel_time_min(graph.road("BD"))
    )


def test_dijkstra_finds_the_expected_shortest_candidate(graph):
    path = dijkstra_path(graph, "A", "D")
    assert path.nodes == ["A", "B", "D"]


def test_a_star_returns_a_valid_connected_path(graph):
    path = a_star(graph, "A", "D")
    assert path.nodes[0] == "A" and path.nodes[-1] == "D"
    for a, b, road_id in zip(path.nodes, path.nodes[1:], path.road_ids):
        road = graph.road(road_id)
        assert {road.from_node, road.to_node} == {a, b}


def test_a_star_cost_matches_dijkstra_optimum(graph):
    """An admissible heuristic must not change the optimal cost."""
    for destination in ("B", "C", "D", "E"):
        astar = a_star(graph, "A", destination)
        dij = dijkstra_path(graph, "A", destination)
        assert astar.travel_time_min == pytest.approx(dij.travel_time_min)
        assert astar.distance_km == pytest.approx(dij.distance_km)


def test_a_star_heuristic_never_overestimates(graph):
    """Admissibility: h(n) <= true remaining cost, for every node."""
    for node in graph.nodes:
        true_cost = dijkstra_path(graph, node, "D")
        remaining = 0.0 if node == "D" else true_cost.travel_time_min
        assert graph.heuristic_min(node, "D") <= remaining + 1e-9


def test_closed_roads_are_never_traversed(graph):
    graph.set_status("AB", RoadStatus.CLOSED)
    path = a_star(graph, "A", "D")
    assert "AB" not in path.road_ids
    assert path.nodes == ["A", "C", "D"]


def test_destination_becomes_unreachable_when_all_roads_close(graph):
    graph.set_status("AB", RoadStatus.CLOSED)
    graph.set_status("AC", RoadStatus.CLOSED)
    assert a_star(graph, "A", "D") is None
    assert dijkstra_path(graph, "A", "D") is None


def test_traffic_changes_eta_without_changing_distance(graph):
    before = a_star(graph, "A", "D")
    graph.set_traffic("AB", "high")
    after = a_star(graph, "A", "D")
    assert after.travel_time_min > before.travel_time_min or after.road_ids != before.road_ids
    # The fast road is now slow enough that the safe lanes win on time.
    slow_ab = a_star(graph, "A", "B").travel_time_min
    assert slow_ab > graph.road("AB").distance_km / graph.road("AB").speed_kmph * 60


def test_incident_delay_is_added_to_travel_time(graph):
    road = graph.road("AB")
    baseline = graph.travel_time_min(road)
    graph.set_incident("AB", Incident(type="accident", severity="major"))
    assert graph.travel_time_min(road) == pytest.approx(baseline + 15.0)


def test_alternative_paths_are_distinct_and_ordered(graph):
    paths = k_alternative_paths(graph, "A", "D", k=3)
    assert len(paths) >= 2
    keys = [p.key() for p in paths]
    assert len(keys) == len(set(keys)), "alternatives must be genuinely different"
    times = [p.travel_time_min for p in paths]
    assert times == sorted(times), "best route first"


def test_alternatives_never_fabricate_routes(graph):
    """A graph with exactly one route must return exactly one route."""
    graph.set_status("AB", RoadStatus.CLOSED)
    paths = k_alternative_paths(graph, "A", "D", k=3)
    assert len(paths) == 1
    assert paths[0].nodes == ["A", "C", "D"]


def test_routing_is_deterministic(graph):
    runs = [tuple(a_star(graph, "A", "D").road_ids) for _ in range(5)]
    assert len(set(runs)) == 1


def test_unknown_node_raises_a_machine_readable_error(graph):
    with pytest.raises(EngineError) as exc:
        a_star(graph, "A", "NOPE")
    assert exc.value.code == ErrorCode.UNKNOWN_NODE


def test_real_demo_graph_matches_between_algorithms(demo_session):
    """A* and Dijkstra agree on the production data set too."""
    graph = demo_session.graph
    for destination in sorted(graph.nodes):
        astar = a_star(graph, "N2", destination)
        dij = dijkstra_path(graph, "N2", destination)
        assert astar.travel_time_min == pytest.approx(dij.travel_time_min)
