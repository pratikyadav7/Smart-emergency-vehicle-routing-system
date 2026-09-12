"""
POST /reroute

Request body::

    {
      "emergency": { ... same shape as /analyze ... },
      "ambulance": {"current_node": "N1", "ambulance_id": "A01"},
      "current_route": {"route_id": "...", "nodes": [...], "edges": [...],
                        "hospital_id": "H2"},
      "environment": {"chaos_events": [ ... ]},
      "trigger": {"type": "ACCIDENT", "road_id": "R10", ...}   # optional
    }

Returns the recalculated recommendation plus the before/after comparison the
dispatcher confirms against. The routing logic is shared with ``/analyze`` -
this handler only supplies a different origin and the current-route context.
"""

from typing import Any, Dict, Optional

from ...errors import EngineError, ErrorCode
from ..common import api_response, handle_engine_error, parse_body
from ..analyze.handler import build_session


def handler(event: Any, context: Optional[Any] = None) -> Dict[str, Any]:
    try:
        body = parse_body(event)
        emergency_payload = body.get("emergency")
        if not isinstance(emergency_payload, dict):
            raise EngineError(
                ErrorCode.INVALID_EMERGENCY,
                "/reroute requires the original 'emergency' object.",
            )

        session = build_session(body)
        session.create_emergency(emergency_payload)

        ambulance = body.get("ambulance") or {}
        current_node = ambulance.get("current_node") or body.get("current_node")
        if not current_node:
            raise EngineError(
                ErrorCode.INVALID_REQUEST,
                "/reroute requires the ambulance's current node.",
            )

        session.active_route = body.get("current_route")
        result = session.engine.reroute(
            session.emergency,
            current_node=current_node,
            current_route=body.get("current_route"),
            trigger=body.get("trigger") or session.last_chaos_event,
        )
        result["history"] = session.history.as_list()
        return api_response(result)
    except EngineError as error:
        return handle_engine_error(error)
