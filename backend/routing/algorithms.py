"""
Graph search: Dijkstra, A* and a deterministic alternative-route generator.

Both searches minimise *travel time* (see :meth:`RoadGraph.travel_time_min`),
so traffic levels and incident delays are part of the cost, not an
afterthought applied to the result.

Determinism: the priority queues break ties on ``(cost, node_id)`` and
adjacency is iterated in sorted road-id order, so the same graph state always
yields byte-identical paths.
"""

import heapq
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Set, Tuple

from .. import config
from ..errors import EngineError, ErrorCode
from .graph import RoadGraph

INFINITY = float("inf")


@dataclass
class Path:
    """A concrete, traversable route through the graph."""

    nodes: List[str]
    road_ids: List[str] = field(default_factory=list)
    distance_km: float = 0.0
    travel_time_min: float = 0.0

    @property
    def origin(self) -> str:
        return self.nodes[0]

    @property
    def destination(self) -> str:
        return self.nodes[-1]

    @property
    def hop_count(self) -> int:
        return len(self.road_ids)

    def key(self) -> Tuple[str, ...]:
        """Identity used for de-duplication."""
        return tuple(self.road_ids)

    def to_dict(self) -> Dict[str, object]:
        return {
            "nodes": list(self.nodes),
            "roads": list(self.road_ids),
            "distance_km": round(self.distance_km, config.ROUND_DIGITS),
            "travel_time_min": round(self.travel_time_min, config.ROUND_DIGITS),
        }


def _measure(graph: RoadGraph, nodes: List[str], road_ids: List[str]) -> Path:
    roads = [graph.road(rid) for rid in road_ids]
    return Path(
        nodes=nodes,
        road_ids=road_ids,
        distance_km=sum(r.distance_km for r in roads),
        travel_time_min=sum(graph.travel_time_min(r) for r in roads),
    )


def _reconstruct(
    graph: RoadGraph,
    came_from: Dict[str, Tuple[str, str]],
    origin: str,
    destination: str,
) -> Path:
    """Walk the predecessor map backwards into a :class:`Path`."""
    nodes = [destination]
    road_ids: List[str] = []
    cursor = destination
    while cursor != origin:
        previous, road_id = came_from[cursor]
        road_ids.append(road_id)
        nodes.append(previous)
        cursor = previous
    nodes.reverse()
    road_ids.reverse()
    return _measure(graph, nodes, road_ids)


def dijkstra(
    graph: RoadGraph,
    origin: str,
    blocked_roads: Optional[Iterable[str]] = None,
) -> Tuple[Dict[str, float], Dict[str, Tuple[str, str]]]:
    """Single-source shortest travel time to every reachable node.

    Used to shortlist hospitals: one sweep prices every candidate destination,
    which is exactly what Dijkstra is good at and A* is not.
    """
    if not graph.has_node(origin):
        raise EngineError(ErrorCode.UNKNOWN_NODE, f"Unknown origin node {origin!r}.", node_id=origin)

    distances: Dict[str, float] = {origin: 0.0}
    came_from: Dict[str, Tuple[str, str]] = {}
    settled: Set[str] = set()
    queue: List[Tuple[float, str]] = [(0.0, origin)]

    while queue:
        cost, current = heapq.heappop(queue)
        if current in settled:
            continue
        settled.add(current)

        for neighbour, road in graph.neighbours(current, blocked_roads):
            if neighbour in settled:
                continue
            candidate = cost + graph.travel_time_min(road)
            if candidate < distances.get(neighbour, INFINITY):
                distances[neighbour] = candidate
                came_from[neighbour] = (current, road.id)
                heapq.heappush(queue, (candidate, neighbour))

    return distances, came_from


def dijkstra_path(
    graph: RoadGraph,
    origin: str,
    destination: str,
    blocked_roads: Optional[Iterable[str]] = None,
) -> Optional[Path]:
    """Shortest-travel-time path via Dijkstra (reference for A* correctness)."""
    if not graph.has_node(destination):
        raise EngineError(
            ErrorCode.UNKNOWN_NODE, f"Unknown destination node {destination!r}.", node_id=destination
        )
    if origin == destination:
        return Path(nodes=[origin])
    distances, came_from = dijkstra(graph, origin, blocked_roads)
    if destination not in distances:
        return None
    return _reconstruct(graph, came_from, origin, destination)


def a_star(
    graph: RoadGraph,
    origin: str,
    destination: str,
    blocked_roads: Optional[Iterable[str]] = None,
) -> Optional[Path]:
    """Shortest-travel-time path to a single destination, guided by a heuristic.

    The heuristic is straight-line distance at the network's top speed, which
    is admissible (never overestimates), so A* returns the same optimal cost
    as Dijkstra while expanding fewer nodes.
    """
    if not graph.has_node(origin):
        raise EngineError(ErrorCode.UNKNOWN_NODE, f"Unknown origin node {origin!r}.", node_id=origin)
    if not graph.has_node(destination):
        raise EngineError(
            ErrorCode.UNKNOWN_NODE, f"Unknown destination node {destination!r}.", node_id=destination
        )
    if origin == destination:
        return Path(nodes=[origin])

    g_score: Dict[str, float] = {origin: 0.0}
    came_from: Dict[str, Tuple[str, str]] = {}
    settled: Set[str] = set()
    start_h = graph.heuristic_min(origin, destination)
    queue: List[Tuple[float, float, str]] = [(start_h, 0.0, origin)]

    while queue:
        _, cost, current = heapq.heappop(queue)
        if current in settled:
            continue
        if current == destination:
            return _reconstruct(graph, came_from, origin, destination)
        settled.add(current)

        for neighbour, road in graph.neighbours(current, blocked_roads):
            if neighbour in settled:
                continue
            candidate = cost + graph.travel_time_min(road)
            if candidate < g_score.get(neighbour, INFINITY):
                g_score[neighbour] = candidate
                came_from[neighbour] = (current, road.id)
                priority = candidate + graph.heuristic_min(neighbour, destination)
                heapq.heappush(queue, (priority, candidate, neighbour))

    return None


def k_alternative_paths(
    graph: RoadGraph,
    origin: str,
    destination: str,
    k: int = config.MAX_ROUTES_PER_HOSPITAL,
    blocked_roads: Optional[Iterable[str]] = None,
) -> List[Path]:
    """Up to *k* genuinely distinct routes, best-first.

    Deterministic road-removal search (the first level of Yen's algorithm):
    take the optimal A* path, then re-plan with each of its roads removed in
    turn. Every result is a real path found by the same search - no route is
    ever synthesised, and if the graph only supports one route, one route is
    returned.
    """
    if k <= 0:
        return []

    best = a_star(graph, origin, destination, blocked_roads)
    if best is None:
        return []

    blocked = set(blocked_roads or ())
    found: List[Path] = [best]
    seen = {best.key()}

    for road_id in best.road_ids:
        if len(found) >= k:
            break
        candidate = a_star(graph, origin, destination, blocked | {road_id})
        if candidate is None or candidate.key() in seen:
            continue
        seen.add(candidate.key())
        found.append(candidate)

    # Deterministic ordering: fastest first, then hop count, then road ids.
    found.sort(key=lambda p: (round(p.travel_time_min, 6), p.hop_count, p.key()))
    return found[:k]
