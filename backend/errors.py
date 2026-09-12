"""
Machine-readable failure states.

The engine never invents a hospital, a route or an ETA. When it cannot
produce a real answer it raises :class:`EngineError`, which the Lambda
handlers serialise into a stable ``{"error": {...}}`` envelope so the
frontend can branch on ``code`` and show ``message``.
"""

from typing import Any, Dict, Optional


class ErrorCode:
    """Stable string codes. Values are part of the API contract."""

    INVALID_REQUEST = "INVALID_REQUEST"
    INVALID_EMERGENCY = "INVALID_EMERGENCY"
    MISSING_ORIGIN = "MISSING_ORIGIN"
    UNKNOWN_NODE = "UNKNOWN_NODE"
    UNKNOWN_ROAD = "UNKNOWN_ROAD"
    UNKNOWN_HOSPITAL = "UNKNOWN_HOSPITAL"
    UNSUPPORTED_REQUIREMENT = "UNSUPPORTED_REQUIREMENT"
    NO_ELIGIBLE_HOSPITAL = "NO_ELIGIBLE_HOSPITAL"
    NO_FEASIBLE_ROUTE = "NO_FEASIBLE_ROUTE"
    INVALID_CHAOS_EVENT = "INVALID_CHAOS_EVENT"
    SIMULATION_NOT_STARTED = "SIMULATION_NOT_STARTED"


class EngineError(Exception):
    """An expected, explainable failure state (not a crash)."""

    def __init__(self, code: str, message: str, **details: Any) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details: Dict[str, Any] = details

    def to_dict(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {"code": self.code, "message": self.message}
        if self.details:
            payload["details"] = self.details
        return payload

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"EngineError({self.code}: {self.message})"


def require(condition: bool, code: str, message: str, **details: Any) -> None:
    """Defensive-validation helper: raise :class:`EngineError` unless *condition*."""
    if not condition:
        raise EngineError(code, message, **details)


def error_response(error: EngineError, request_id: Optional[str] = None) -> Dict[str, Any]:
    """Uniform error envelope shared by both Lambda handlers."""
    body: Dict[str, Any] = {"status": "error", "error": error.to_dict()}
    if request_id:
        body["request_id"] = request_id
    return body
