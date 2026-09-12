"""
Explainable, deterministic hospital-route scoring.

Every candidate is a *pair* (hospital, route). Eight named components are
each normalised to 0-100 (higher is always better, including the incident
component, which measures "how clear the road is"), then combined with the
priority-dependent weights in :mod:`backend.config`:

    total = sum(component[k] * weight[k] for k in components)

Because every weight profile sums to 1.0, the total is itself a 0-100 number
the dispatcher can read directly, and the breakdown always accounts for it
exactly. There are no hidden constants in this module - they all live in
``config``.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .. import config
from ..models.emergency import Emergency
from ..models.hospital import Hospital
from .algorithms import Path
from .graph import RoadGraph
from .hospitals import medical_fit_score, preference_score, readiness_score

#: The component keys, in the order they are presented to the dispatcher.
COMPONENT_KEYS = (
    "medical_fit",
    "hospital_readiness",
    "travel_time",
    "traffic",
    "road_capacity",
    "safety",
    "incident_penalty",
    "priority_preference",
)


@dataclass
class RouteMetrics:
    """Physical facts about a route, independent of any weighting."""

    distance_km: float
    eta_min: float
    traffic_score: float
    capacity_score: float
    safety_score: float
    clear_road_score: float
    incident_delay_min: float
    dominant_traffic: str
    incidents: List[Dict[str, Any]] = field(default_factory=list)

    @property
    def has_incident(self) -> bool:
        return bool(self.incidents)

    def to_dict(self) -> Dict[str, Any]:
        rd = config.ROUND_DIGITS
        return {
            "distance_km": round(self.distance_km, rd),
            "eta_minutes": round(self.eta_min, rd),
            "traffic_condition": self.dominant_traffic,
            "traffic_score": round(self.traffic_score, rd),
            "capacity_score": round(self.capacity_score, rd),
            "safety_score": round(self.safety_score, rd),
            "clear_road_score": round(self.clear_road_score, rd),
            "incident_delay_minutes": round(self.incident_delay_min, rd),
            "incident_impact": self.incidents,
        }


@dataclass
class ScoreBreakdown:
    """A total plus the exact per-component contributions behind it."""

    total: float
    components: Dict[str, float]
    weights: Dict[str, float]
    contributions: Dict[str, float]
    profile: str

    def to_dict(self) -> Dict[str, Any]:
        rd = config.ROUND_DIGITS
        return {
            "total": round(self.total, rd),
            "profile": self.profile,
            "components": {k: round(v, rd) for k, v in self.components.items()},
            "weights": {k: round(v, 4) for k, v in self.weights.items()},
            "contributions": {k: round(v, rd) for k, v in self.contributions.items()},
        }


def _weighted_average(values: List[float], weights: List[float]) -> float:
    """Distance-weighted mean so a long bad road outweighs a short good one."""
    total_weight = sum(weights)
    if total_weight <= 0:
        return sum(values) / len(values) if values else 0.0
    return sum(v * w for v, w in zip(values, weights)) / total_weight


def compute_route_metrics(graph: RoadGraph, path: Path) -> RouteMetrics:
    """Turn a :class:`Path` into the physical metrics the score is built from."""
    roads = [graph.road(rid) for rid in path.road_ids]

    if not roads:  # origin already at the destination
        return RouteMetrics(
            distance_km=0.0,
            eta_min=0.0,
            traffic_score=100.0,
            capacity_score=100.0,
            safety_score=100.0,
            clear_road_score=100.0,
            incident_delay_min=0.0,
            dominant_traffic="low",
        )

    lengths = [r.distance_km for r in roads]
    traffic = _weighted_average(
        [config.TRAFFIC_SCORE.get(r.traffic, config.UNKNOWN_LEVEL_SCORE) for r in roads], lengths
    )
    capacity = _weighted_average(
        [config.CAPACITY_SCORE.get(r.capacity, config.UNKNOWN_LEVEL_SCORE) for r in roads], lengths
    )
    safety = _weighted_average([float(r.safety) for r in roads], lengths)

    incidents = [
        {
            "road_id": r.id,
            "road_name": r.name,
            "type": r.incident.type,
            "severity": r.incident.severity,
            "delay_minutes": r.incident.delay_minutes,
        }
        for r in roads
        if r.has_incident
    ]
    incident_delay = sum(i["delay_minutes"] for i in incidents)
    penalty = sum(r.incident.score_penalty for r in roads if r.has_incident)
    clear_road = max(0.0, 100.0 - penalty)

    # The worst traffic level anywhere on the route is what a dispatcher cares
    # about, not the average label.
    order = {"low": 0, "medium": 1, "high": 2}
    dominant = max((r.traffic for r in roads), key=lambda t: order.get(t, 1))

    return RouteMetrics(
        distance_km=path.distance_km,
        eta_min=path.travel_time_min,
        traffic_score=traffic,
        capacity_score=capacity,
        safety_score=safety,
        clear_road_score=clear_road,
        incident_delay_min=incident_delay,
        dominant_traffic=dominant,
        incidents=incidents,
    )


def travel_time_score(eta_min: float) -> float:
    """Linear decay to zero at ``ETA_REFERENCE_MIN``; never negative."""
    ratio = eta_min / config.ETA_REFERENCE_MIN
    return max(0.0, min(100.0, (1.0 - ratio) * 100.0))


def score_candidate(
    hospital: Hospital,
    metrics: RouteMetrics,
    emergency: Emergency,
    weights: Optional[Dict[str, float]] = None,
) -> ScoreBreakdown:
    """Combine hospital state and route metrics into one explainable score."""
    weights = dict(weights) if weights else config.weights_for_priority(emergency.priority)

    components = {
        "medical_fit": medical_fit_score(hospital, emergency.requirements),
        "hospital_readiness": readiness_score(hospital),
        "travel_time": travel_time_score(metrics.eta_min),
        "traffic": metrics.traffic_score,
        "road_capacity": metrics.capacity_score,
        "safety": metrics.safety_score,
        "incident_penalty": metrics.clear_road_score,
        "priority_preference": preference_score(hospital, emergency.preferred_hospital_id),
    }

    contributions = {key: components[key] * weights.get(key, 0.0) for key in COMPONENT_KEYS}
    total = sum(contributions.values())

    return ScoreBreakdown(
        total=total,
        components={k: components[k] for k in COMPONENT_KEYS},
        weights={k: weights.get(k, 0.0) for k in COMPONENT_KEYS},
        contributions=contributions,
        profile=config.weight_profile_name(emergency.priority),
    )
