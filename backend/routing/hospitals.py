"""
Medical eligibility.

Suitability is a hard gate evaluated *before* any preference or distance
consideration: a dispatcher cannot route an ICU + trauma patient to a
facility that has neither, however close it is or however explicitly it was
requested. The preferred hospital is only ever a tie-break applied to
hospitals that already passed this gate.
"""

import json
import os
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional

from .. import config
from ..errors import EngineError, ErrorCode
from ..models.emergency import Emergency
from ..models.hospital import Hospital
from .graph import DATA_DIR


class RejectionReason:
    NOT_ACCEPTING = "NOT_ACCEPTING"
    NO_CAPACITY = "NO_CAPACITY"
    MISSING_CAPABILITY = "MISSING_CAPABILITY"


@dataclass
class EligibilityResult:
    """Explainable outcome of the medical-suitability gate."""

    eligible: List[Hospital]
    rejected: List[Dict[str, Any]]
    preferred_rejected: Optional[Dict[str, Any]] = None

    @property
    def has_eligible(self) -> bool:
        return bool(self.eligible)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "eligible": [h.to_dict() for h in self.eligible],
            "rejected": list(self.rejected),
            "preferred_rejected": self.preferred_rejected,
        }


def load_hospitals(hospitals_path: Optional[str] = None) -> Dict[str, Hospital]:
    hospitals_path = hospitals_path or os.path.join(DATA_DIR, "hospitals.json")
    with open(hospitals_path, encoding="utf-8") as handle:
        payload = json.load(handle)
    return {h["id"]: Hospital.from_dict(h) for h in payload.get("hospitals", [])}


def _rejection(hospital: Hospital, reason: str, detail: str, **extra: Any) -> Dict[str, Any]:
    return {
        "hospital_id": hospital.id,
        "hospital_name": hospital.name,
        "reason": reason,
        "detail": detail,
        **extra,
    }


def evaluate_eligibility(
    hospitals: Iterable[Hospital],
    emergency: Emergency,
) -> EligibilityResult:
    """Split hospitals into medically eligible and rejected-with-a-reason."""
    eligible: List[Hospital] = []
    rejected: List[Dict[str, Any]] = []

    for hospital in sorted(hospitals, key=lambda h: h.id):
        if not hospital.accepting:
            rejected.append(
                _rejection(
                    hospital,
                    RejectionReason.NOT_ACCEPTING,
                    f"{hospital.name} is not currently accepting emergency admissions.",
                )
            )
            continue

        if not hospital.has_capacity:
            rejected.append(
                _rejection(
                    hospital,
                    RejectionReason.NO_CAPACITY,
                    f"{hospital.name} has no emergency beds available.",
                    emergency_beds=hospital.emergency_beds,
                )
            )
            continue

        missing = hospital.missing_capabilities(emergency.requirements)
        if missing:
            rejected.append(
                _rejection(
                    hospital,
                    RejectionReason.MISSING_CAPABILITY,
                    f"{hospital.name} lacks required capability: {', '.join(missing)}.",
                    missing_capabilities=missing,
                )
            )
            continue

        eligible.append(hospital)

    preferred_rejected = None
    if emergency.preferred_hospital_id:
        preferred_rejected = next(
            (r for r in rejected if r["hospital_id"] == emergency.preferred_hospital_id), None
        )

    return EligibilityResult(
        eligible=eligible, rejected=rejected, preferred_rejected=preferred_rejected
    )


def validate_preferred_hospital(
    hospitals: Dict[str, Hospital], emergency: Emergency
) -> None:
    """A preference for a hospital that does not exist is a client bug, not a soft miss."""
    preferred = emergency.preferred_hospital_id
    if preferred and preferred not in hospitals:
        raise EngineError(
            ErrorCode.UNKNOWN_HOSPITAL,
            f"Preferred hospital {preferred!r} does not exist.",
            hospital_id=preferred,
            known=sorted(hospitals),
        )


def readiness_score(hospital: Hospital) -> float:
    """0-100 view of how ready a hospital is to receive another patient."""
    if not hospital.accepting:
        return 0.0
    ratio = hospital.emergency_beds / float(config.READINESS_REFERENCE_BEDS)
    return max(0.0, min(100.0, ratio * 100.0))


def medical_fit_score(hospital: Hospital, requirements: Iterable[str]) -> float:
    """0-100 medical suitability.

    Split into "covers what this patient needs right now" (the hard
    requirement, always satisfied by an eligible hospital) and "has depth if
    the patient deteriorates", which is what actually separates two eligible
    facilities.
    """
    requirements = list(requirements)
    if requirements:
        met = sum(1 for r in requirements if hospital.has_capability(r))
        coverage = met / len(requirements)
    else:
        coverage = 1.0

    all_capabilities = sorted(Hospital.CAPABILITY_ATTRS)
    depth = sum(1 for c in all_capabilities if hospital.has_capability(c)) / len(all_capabilities)

    return (
        coverage * config.MEDICAL_FIT_REQUIRED_WEIGHT
        + depth * config.MEDICAL_FIT_DEPTH_WEIGHT
    )


def preference_score(hospital: Hospital, preferred_hospital_id: Optional[str]) -> float:
    """Soft preference, applied only to hospitals that already passed the gate."""
    if not preferred_hospital_id:
        return config.PREFERENCE_SCORE_NO_REQUEST
    if hospital.id == preferred_hospital_id:
        return config.PREFERENCE_SCORE_MATCHES_REQUEST
    return config.PREFERENCE_SCORE_OTHER
