"""
POST /analyze

Request body (see ``docs/api-contract.md``)::

    {
      "emergency": {
        "id": "E001", "origin_node": "N2", "priority": 10,
        "requirements": ["icu", "trauma"],
        "preferred_hospital_id": "H1", "ambulance_id": "A01"
      },
      "environment": {"chaos_events": [ ... ]}   # optional, replayed first
    }

Returns the recommendation envelope: selected hospital, recommended route,
alternatives, score breakdowns, explanations and the eligibility audit.
"""

from typing import Any, Dict, Optional

from ...errors import EngineError, ErrorCode
from ...session import DispatchSession
from ..common import api_response, handle_engine_error, parse_body


def build_session(body: Dict[str, Any]) -> DispatchSession:
    """Construct a session and replay any environment state the caller sent.

    Lambdas are stateless, so the caller (Person B) passes the accumulated
    chaos events back in and the engine rebuilds the same world every time.
    """
    session = DispatchSession()
    environment = body.get("environment") or {}
    for event in environment.get("chaos_events", []) or []:
        session.inject_chaos(event)
    return session


def handler(event: Any, context: Optional[Any] = None) -> Dict[str, Any]:
    try:
        body = parse_body(event)
        emergency_payload = body.get("emergency", body)
        if not isinstance(emergency_payload, dict):
            raise EngineError(ErrorCode.INVALID_EMERGENCY, "'emergency' must be a JSON object.")

        session = build_session(body)
        session.create_emergency(emergency_payload)
        result = session.analyze()
        result["history"] = session.history.as_list()
        return api_response(result)
    except EngineError as error:
        return handle_engine_error(error)
