"""
Human-readable reasons, generated from live score components.

Nothing here is a canned sentence keyed off a route id: every phrase is
derived from the candidate's actual metrics and breakdown, so the text stays
correct after Chaos Mode changes the world. Implementation details (weights,
road ids, algorithm names) stay out of the dispatcher-facing strings.
"""

from typing import Any, Dict, List, Optional

from ..models.emergency import Emergency
from ..models.hospital import Hospital
from .scoring import RouteMetrics, ScoreBreakdown

#: Thresholds for turning a 0-100 sub-score into a word a dispatcher reads.
_BANDS = ((85.0, "excellent"), (70.0, "strong"), (55.0, "acceptable"), (0.0, "poor"))

_REQUIREMENT_LABELS = {"icu": "ICU", "trauma": "trauma", "cardiac": "cardiac"}


def band(value: float) -> str:
    for threshold, label in _BANDS:
        if value >= threshold:
            return label
    return "poor"


def requirement_phrase(requirements: List[str]) -> str:
    labels = [_REQUIREMENT_LABELS.get(r, r) for r in requirements]
    if not labels:
        return "general emergency care"
    if len(labels) == 1:
        return labels[0]
    return " + ".join(labels)


def explain_hospital(hospital: Hospital, emergency: Emergency) -> str:
    """Why this destination is medically appropriate."""
    needs = requirement_phrase(emergency.requirements)
    sentence = (
        f"Selected because {hospital.name} satisfies the required "
        f"{needs} capability and is currently accepting patients "
        f"({hospital.emergency_beds} emergency bed"
        f"{'s' if hospital.emergency_beds != 1 else ''} free)."
    )
    if emergency.preferred_hospital_id == hospital.id:
        sentence += " This also matches the hospital the dispatcher requested."
    return sentence


def explain_route(metrics: RouteMetrics, breakdown: ScoreBreakdown, graph_names: List[str]) -> str:
    """Why this route won, phrased from its own component profile."""
    parts: List[str] = [f"ETA {round(metrics.eta_min, 1)} minutes over {round(metrics.distance_km, 1)} km"]
    parts.append(f"{band(breakdown.components['safety'])} safety profile")
    parts.append(f"{metrics.dominant_traffic} congestion on the busiest segment")

    if metrics.has_incident:
        worst = max(metrics.incidents, key=lambda i: i["delay_minutes"])
        parts.append(
            f"an active {worst['severity']} {worst['type']} on {worst['road_name']} "
            f"adding about {round(worst['delay_minutes'], 1)} minutes"
        )
    else:
        parts.append("no active incidents")

    via = " via " + " -> ".join(graph_names) if graph_names else ""
    return "Route" + via + ": " + ", ".join(parts) + "."


def explain_alternative(
    alternative: Dict[str, Any], recommended: Dict[str, Any]
) -> str:
    """Why a feasible alternative was not the recommendation."""
    alt_eta = alternative["eta_minutes"]
    best_eta = recommended["eta_minutes"]
    alt_score = alternative["score"]
    best_score = recommended["score"]

    if alternative["incident_impact"]:
        worst = max(alternative["incident_impact"], key=lambda i: i["delay_minutes"])
        return (
            f"Feasible, but an active {worst['severity']} {worst['type']} on "
            f"{worst['road_name']} adds delay and lowers its score "
            f"({alt_score} vs {best_score})."
        )
    if alt_eta > best_eta:
        return (
            f"Feasible, but slower: {alt_eta} minutes against {best_eta} minutes "
            f"for the recommended route."
        )
    if alt_eta < best_eta:
        return (
            f"Faster on paper ({alt_eta} vs {best_eta} minutes) but scored lower "
            f"({alt_score} vs {best_score}) on safety, road quality or hospital readiness."
        )
    return f"Feasible, but scored lower overall ({alt_score} vs {best_score})."


def explain_preference_override(preferred_rejected: Optional[Dict[str, Any]]) -> Optional[str]:
    """Dispatcher-facing warning when the requested hospital could not be used."""
    if not preferred_rejected:
        return None
    return (
        f"Requested hospital {preferred_rejected['hospital_name']} was not used: "
        f"{preferred_rejected['detail']} Medical suitability is checked before preference."
    )


def explain_reroute(
    old_route: Dict[str, Any],
    new_route: Dict[str, Any],
    trigger: Optional[Dict[str, Any]],
    destination_changed: bool,
    new_hospital_name: str,
) -> str:
    """Why the engine is proposing a different route (or destination) now."""
    cause = "current road conditions changed"
    if trigger:
        if trigger.get("type") == "ROAD_CLOSURE":
            cause = f"{trigger.get('road_name', trigger.get('road_id'))} is now closed"
        elif trigger.get("type") == "ACCIDENT":
            cause = (
                f"a {trigger.get('severity', 'reported')} accident is blocking "
                f"{trigger.get('road_name', trigger.get('road_id'))}"
            )
        elif trigger.get("type") == "TRAFFIC_SPIKE":
            cause = f"traffic surged on {trigger.get('road_name', trigger.get('road_id'))}"
        elif trigger.get("type") == "HOSPITAL_CAPACITY":
            cause = f"{trigger.get('hospital_name', trigger.get('hospital_id'))} changed its capacity"

    old_eta = old_route.get("eta_minutes")
    new_eta = new_route["eta_minutes"]
    if old_eta is None:
        # The previous route is no longer traversable at all, so there is no
        # old ETA to compare against - say that rather than inventing one.
        eta_phrase = (
            f"the previous route is no longer passable and the new ETA is {new_eta} minutes"
        )
    elif new_eta > old_eta:
        eta_phrase = f"ETA increases from {old_eta} to {new_eta} minutes"
    elif new_eta < old_eta:
        eta_phrase = f"ETA improves from {old_eta} to {new_eta} minutes"
    else:
        eta_phrase = f"ETA is unchanged at {new_eta} minutes"

    destination_phrase = (
        f" The destination also changed to {new_hospital_name}." if destination_changed else ""
    )
    return (
        f"Rerouting because {cause}. The previous route is no longer the best available option; "
        f"{eta_phrase}.{destination_phrase}"
    )
