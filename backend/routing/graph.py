"""
Deterministic road-graph representation.

Roads are physically bidirectional in this prototype, so each record in
``roads.json`` becomes two traversable directions sharing one :class:`Road`
object - closing a road or attaching an incident therefore affects both
directions automatically.

Travel time is derived, never stored:

    effective_speed = speed_kmph * TRAFFIC_SPEED_FACTOR[traffic]
    travel_time_min = distance_km / effective_speed * 60 + incident_delay

which means a traffic spike or an accident changes the actual ETA rather
than only a cosmetic score.
"""

import json
import math
import os
from typing import Any, Dict, Iterable, Iterator, List, Optional, Tuple

from .. import config
from ..errors import EngineError, ErrorCode
from ..models.incident import Incident
from ..models.road import Node, Road

DATA_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "data")
)

EARTH_RADIUS_KM = 6371.0


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in kilometres."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))


class RoadGraph:
    """Nodes, roads, adjacency and the cost model used by every algorithm."""

    def __init__(self, nodes: Iterable[Node], roads: Iterable[Road], city: str = "") -> None:
        self.city = city
        self.nodes: Dict[str, Node] = {n.id: n for n in nodes}
        self.roads: Dict[str, Road] = {}
        self._adjacency: Dict[str, List[Tuple[str, Road]]] = {n: [] for n in self.nodes}

        for road in roads:
            self._register(road)

        # Admissible-heuristic ceiling: nothing can travel faster than the
        # fastest road in the network under free-flow conditions.
        self.max_speed_kmph = max(
            (r.speed_kmph for r in self.roads.values()), default=config.MIN_EFFECTIVE_SPEED_KMPH
        )

    # -- construction --------------------------------------------------

    def _register(self, road: Road) -> None:
        for endpoint in (road.from_node, road.to_node):
            if endpoint not in self.nodes:
                raise EngineError(
                    ErrorCode.UNKNOWN_NODE,
                    f"Road {road.id} references unknown node {endpoint!r}.",
                    road_id=road.id,
                    node_id=endpoint,
                )
        a, b = self.nodes[road.from_node], self.nodes[road.to_node]
        road.distance_km = haversine_km(a.lat, a.lon, b.lat, b.lon)
        self.roads[road.id] = road
        self._adjacency[road.from_node].append((road.to_node, road))
        self._adjacency[road.to_node].append((road.from_node, road))

    @classmethod
    def from_files(cls, roads_path: Optional[str] = None) -> "RoadGraph":
        roads_path = roads_path or os.path.join(DATA_DIR, "roads.json")
        with open(roads_path, encoding="utf-8") as handle:
            payload = json.load(handle)
        return cls.from_dict(payload)

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "RoadGraph":
        nodes = [Node.from_dict(n) for n in payload.get("nodes", [])]
        roads = [Road.from_dict(e) for e in payload.get("edges", payload.get("roads", []))]
        return cls(nodes, roads, city=payload.get("city", ""))

    # -- lookups -------------------------------------------------------

    def node(self, node_id: str) -> Node:
        node = self.nodes.get(node_id)
        if node is None:
            raise EngineError(
                ErrorCode.UNKNOWN_NODE, f"Unknown node {node_id!r}.", node_id=node_id
            )
        return node

    def road(self, road_id: str) -> Road:
        road = self.roads.get(road_id)
        if road is None:
            raise EngineError(
                ErrorCode.UNKNOWN_ROAD, f"Unknown road {road_id!r}.", road_id=road_id
            )
        return road

    def has_node(self, node_id: str) -> bool:
        return node_id in self.nodes

    def node_name(self, node_id: str) -> str:
        node = self.nodes.get(node_id)
        return node.name if node else node_id

    def road_between(self, a: str, b: str) -> Optional[Road]:
        """The best (fastest currently traversable) road directly joining a and b."""
        candidates = [road for neighbour, road in self._adjacency.get(a, []) if neighbour == b]
        if not candidates:
            return None
        open_roads = [r for r in candidates if r.is_open]
        pool = open_roads or candidates
        # Deterministic tie-break: cheapest first, then road id.
        return min(pool, key=lambda r: (self.travel_time_min(r), r.id))

    def neighbours(
        self, node_id: str, blocked_roads: Optional[Iterable[str]] = None
    ) -> Iterator[Tuple[str, Road]]:
        """Traversable neighbours. Closed roads are never yielded."""
        blocked = set(blocked_roads or ())
        # Sorted for deterministic expansion order regardless of file ordering.
        for neighbour, road in sorted(
            self._adjacency.get(node_id, []), key=lambda pair: (pair[1].id, pair[0])
        ):
            if not road.is_open or road.id in blocked:
                continue
            yield neighbour, road

    # -- cost model ----------------------------------------------------

    def effective_speed_kmph(self, road: Road) -> float:
        factor = config.TRAFFIC_SPEED_FACTOR.get(road.traffic, config.TRAFFIC_SPEED_FACTOR["medium"])
        return max(road.speed_kmph * factor, config.MIN_EFFECTIVE_SPEED_KMPH)

    def travel_time_min(self, road: Road) -> float:
        """Minutes to traverse *road* under current traffic and incidents."""
        base = (road.distance_km / self.effective_speed_kmph(road)) * 60.0
        if road.has_incident:
            base += road.incident.delay_minutes
        return base

    def straight_line_km(self, a: str, b: str) -> float:
        na, nb = self.node(a), self.node(b)
        return haversine_km(na.lat, na.lon, nb.lat, nb.lon)

    def heuristic_min(self, node_id: str, goal_id: str) -> float:
        """Admissible A* heuristic: straight-line distance at the network's top speed.

        No route can beat this, because no road is faster than
        ``max_speed_kmph`` and incidents only ever add time.
        """
        return (self.straight_line_km(node_id, goal_id) / self.max_speed_kmph) * 60.0

    # -- mutation (Chaos Mode) -----------------------------------------

    def set_status(self, road_id: str, status: str) -> Road:
        road = self.road(road_id)
        road.status = status
        return road

    def set_traffic(self, road_id: str, level: str) -> Road:
        road = self.road(road_id)
        if level not in config.TRAFFIC_SPEED_FACTOR:
            raise EngineError(
                ErrorCode.INVALID_CHAOS_EVENT,
                f"Unknown traffic level {level!r}.",
                supported=sorted(config.TRAFFIC_SPEED_FACTOR),
            )
        road.traffic = level
        return road

    def set_incident(self, road_id: str, incident: Optional[Incident]) -> Road:
        road = self.road(road_id)
        road.incident = incident
        return road

    def active_incidents(self) -> List[Dict[str, Any]]:
        return [
            {"road_id": r.id, "road_name": r.name, **r.incident.to_dict()}
            for r in sorted(self.roads.values(), key=lambda r: r.id)
            if r.has_incident
        ]

    def closed_roads(self) -> List[str]:
        return sorted(r.id for r in self.roads.values() if not r.is_open)

    # -- serialisation -------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        return {
            "city": self.city,
            "nodes": [self.nodes[n].to_dict() for n in sorted(self.nodes)],
            "roads": [self.roads[r].to_dict() for r in sorted(self.roads)],
            "closed_roads": self.closed_roads(),
            "active_incidents": self.active_incidents(),
        }
