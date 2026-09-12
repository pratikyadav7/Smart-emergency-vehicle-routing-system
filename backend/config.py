"""
Centralised, tunable configuration for the routing / scoring engine.

Every constant that influences a recommendation lives here so the scoring
model stays auditable: a dispatcher (or a judge) can read one file and know
exactly what the engine optimises for. Nothing in this module depends on the
rest of the package, so tests can monkey-patch values safely.
"""

from typing import Dict

# ---------------------------------------------------------------------------
# Road / traffic physics
# ---------------------------------------------------------------------------

#: Fraction of the free-flow speed limit actually achievable at a traffic level.
TRAFFIC_SPEED_FACTOR: Dict[str, float] = {
    "low": 1.00,
    "medium": 0.75,
    "high": 0.45,
}

#: Never divide by zero / model a road as impassably slow.
MIN_EFFECTIVE_SPEED_KMPH = 5.0

#: Qualitative road attributes mapped onto the shared 0-100 sub-score scale.
TRAFFIC_SCORE: Dict[str, int] = {"low": 100, "medium": 65, "high": 30}
CAPACITY_SCORE: Dict[str, int] = {"high": 100, "medium": 65, "low": 35}

#: Fallback when a data file uses a level we do not recognise.
UNKNOWN_LEVEL_SCORE = 50

# ---------------------------------------------------------------------------
# Incidents
# ---------------------------------------------------------------------------

#: Extra minutes an incident adds to the affected road's travel time.
#: Incidents change the *ETA*, not just an abstract score, so rerouting
#: decisions stay physically meaningful.
INCIDENT_DELAY_MINUTES: Dict[str, float] = {
    "minor": 4.0,
    "moderate": 8.0,
    "major": 15.0,
}

#: Additional 0-100 points removed from the "clear roads" sub-score.
INCIDENT_SEVERITY_PENALTY: Dict[str, float] = {
    "minor": 20.0,
    "moderate": 45.0,
    "major": 80.0,
}

DEFAULT_INCIDENT_SEVERITY = "moderate"

#: An accident degrades the traffic level of the road it happens on.
INCIDENT_TRAFFIC_LEVEL = "high"

#: Multiplier applied to a road's traffic level by a TRAFFIC_SPIKE event.
TRAFFIC_SPIKE_LEVEL = "high"

# ---------------------------------------------------------------------------
# Normalisation references
# ---------------------------------------------------------------------------

#: ETA (minutes) that scores 0 on the travel-time component. Anything longer
#: is clamped to 0 rather than going negative.
ETA_REFERENCE_MIN = 30.0

#: Emergency-bed count that scores 100 on hospital readiness.
READINESS_REFERENCE_BEDS = 8

#: Beds strictly below this make a hospital ineligible.
MIN_REQUIRED_EMERGENCY_BEDS = 1

#: Medical-fit is split between "covers what this patient needs" (hard gate,
#: always satisfied for an eligible hospital) and "has depth if the patient
#: deteriorates" (differentiates two otherwise-eligible hospitals).
MEDICAL_FIT_REQUIRED_WEIGHT = 70.0
MEDICAL_FIT_DEPTH_WEIGHT = 30.0

#: priority_preference sub-scores.
PREFERENCE_SCORE_MATCHES_REQUEST = 100.0
PREFERENCE_SCORE_NO_REQUEST = 60.0
PREFERENCE_SCORE_OTHER = 50.0

# ---------------------------------------------------------------------------
# Scoring weights
# ---------------------------------------------------------------------------
# Higher-priority cases weight medical fit and travel time harder; routine
# cases let safety and road quality carry more of the decision. Each profile
# must sum to 1.0 so the total score is always a 0-100 number.

SCORING_WEIGHTS: Dict[str, float] = {
    "medical_fit": 0.18,
    "hospital_readiness": 0.12,
    "travel_time": 0.28,
    "traffic": 0.10,
    "road_capacity": 0.07,
    "safety": 0.13,
    "incident_penalty": 0.07,
    "priority_preference": 0.05,
}

PRIORITY_WEIGHT_PROFILES: Dict[str, Dict[str, float]] = {
    # priority 8-10: life-threatening, time and medical capability dominate
    "critical": {
        "medical_fit": 0.22,
        "hospital_readiness": 0.13,
        "travel_time": 0.32,
        "traffic": 0.09,
        "road_capacity": 0.05,
        "safety": 0.09,
        "incident_penalty": 0.06,
        "priority_preference": 0.04,
    },
    # priority 4-7: the balanced default
    "urgent": SCORING_WEIGHTS,
    # priority 1-3: stable patient, prefer a safe comfortable transfer
    "routine": {
        "medical_fit": 0.14,
        "hospital_readiness": 0.12,
        "travel_time": 0.18,
        "traffic": 0.11,
        "road_capacity": 0.10,
        "safety": 0.22,
        "incident_penalty": 0.06,
        "priority_preference": 0.07,
    },
}

CRITICAL_PRIORITY_THRESHOLD = 8
ROUTINE_PRIORITY_THRESHOLD = 3


def weight_profile_name(priority: int) -> str:
    """Map an emergency priority (1-10) onto a named weight profile."""
    if priority >= CRITICAL_PRIORITY_THRESHOLD:
        return "critical"
    if priority <= ROUTINE_PRIORITY_THRESHOLD:
        return "routine"
    return "urgent"


def weights_for_priority(priority: int) -> Dict[str, float]:
    """Return the (copied) weight dict used to score a given priority."""
    return dict(PRIORITY_WEIGHT_PROFILES[weight_profile_name(priority)])


# ---------------------------------------------------------------------------
# Route generation
# ---------------------------------------------------------------------------

#: How many routes the UI shows: 1 recommended + 2 alternatives.
MAX_ROUTES_PER_HOSPITAL = 3

#: How many hospitals survive the Dijkstra distance shortlist.
HOSPITAL_SHORTLIST_SIZE = 4

#: Total candidate routes returned by /analyze (recommended + alternatives).
MAX_CANDIDATE_ROUTES = 3

#: Rounding used for every number that crosses the API boundary, so the same
#: request always serialises to byte-identical JSON.
ROUND_DIGITS = 2
