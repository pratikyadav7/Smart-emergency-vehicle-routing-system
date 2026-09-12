"""Medical suitability is a hard gate, evaluated before any preference."""

import pytest

from backend.errors import EngineError, ErrorCode
from backend.models.emergency import Emergency
from backend.models.hospital import Hospital
from backend.routing.hospitals import (
    RejectionReason,
    evaluate_eligibility,
    medical_fit_score,
    preference_score,
    readiness_score,
)


def make_hospital(**overrides):
    base = {
        "id": "HX", "name": "Test Hospital", "node": "D", "emergency_beds": 5,
        "icu_available": True, "trauma_available": True, "cardiac_available": True,
        "accepting": True,
    }
    base.update(overrides)
    return Hospital.from_dict(base)


def emergency(requirements, preferred=None, priority=10):
    return Emergency.from_dict({
        "origin_node": "A", "priority": priority,
        "requirements": requirements, "preferred_hospital_id": preferred,
    })


def test_icu_requirement_excludes_hospital_without_icu():
    result = evaluate_eligibility([make_hospital(icu_available=False)], emergency(["icu"]))
    assert result.eligible == []
    assert result.rejected[0]["reason"] == RejectionReason.MISSING_CAPABILITY
    assert result.rejected[0]["missing_capabilities"] == ["icu"]


def test_trauma_requirement_excludes_hospital_without_trauma():
    result = evaluate_eligibility([make_hospital(trauma_available=False)], emergency(["trauma"]))
    assert result.eligible == []
    assert "trauma" in result.rejected[0]["missing_capabilities"]


def test_cardiac_requirement_excludes_hospital_without_cardiac():
    result = evaluate_eligibility([make_hospital(cardiac_available=False)], emergency(["cardiac"]))
    assert result.eligible == []
    assert "cardiac" in result.rejected[0]["missing_capabilities"]


def test_non_accepting_hospital_is_ineligible_even_when_fully_capable():
    result = evaluate_eligibility([make_hospital(accepting=False)], emergency(["icu"]))
    assert result.eligible == []
    assert result.rejected[0]["reason"] == RejectionReason.NOT_ACCEPTING


def test_zero_emergency_beds_is_ineligible():
    result = evaluate_eligibility([make_hospital(emergency_beds=0)], emergency(["icu"]))
    assert result.eligible == []
    assert result.rejected[0]["reason"] == RejectionReason.NO_CAPACITY


def test_capable_accepting_hospital_is_eligible():
    result = evaluate_eligibility([make_hospital()], emergency(["icu", "trauma"]))
    assert [h.id for h in result.eligible] == ["HX"]
    assert result.rejected == []


def test_preferred_but_unsuitable_hospital_is_reported_as_rejected():
    unsuitable = make_hospital(id="H1", icu_available=False)
    suitable = make_hospital(id="H2")
    result = evaluate_eligibility([unsuitable, suitable], emergency(["icu"], preferred="H1"))

    assert [h.id for h in result.eligible] == ["H2"]
    assert result.preferred_rejected is not None
    assert result.preferred_rejected["hospital_id"] == "H1"


def test_no_suitable_hospital_returns_explicit_empty_state():
    result = evaluate_eligibility(
        [make_hospital(id="H1", icu_available=False), make_hospital(id="H2", accepting=False)],
        emergency(["icu"]),
    )
    assert result.has_eligible is False
    assert len(result.rejected) == 2


def test_unsupported_requirement_is_rejected_at_parse_time():
    with pytest.raises(EngineError) as exc:
        emergency(["telepathy"])
    assert exc.value.code == ErrorCode.UNSUPPORTED_REQUIREMENT


def test_preference_is_a_soft_score_not_a_gate():
    hospital = make_hospital(id="H1")
    assert preference_score(hospital, "H1") > preference_score(hospital, "H2")
    # ...and it never appears in the eligibility gate itself.
    result = evaluate_eligibility([hospital], emergency(["icu"], preferred="H9"))
    assert [h.id for h in result.eligible] == ["H1"]


def test_medical_fit_rewards_capability_depth():
    full = make_hospital(id="HA")
    bare = make_hospital(id="HB", cardiac_available=False)
    requirements = ["icu", "trauma"]
    assert medical_fit_score(full, requirements) > medical_fit_score(bare, requirements)


def test_readiness_scales_with_available_beds():
    assert readiness_score(make_hospital(emergency_beds=8)) == 100.0
    assert readiness_score(make_hospital(emergency_beds=2)) == 25.0
    assert readiness_score(make_hospital(accepting=False)) == 0.0
