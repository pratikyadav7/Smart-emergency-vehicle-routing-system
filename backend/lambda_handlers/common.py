"""Shared plumbing for the Lambda handlers: parsing, envelopes, error mapping."""

import json
from typing import Any, Dict, Optional

from ..errors import EngineError, ErrorCode, error_response

#: EngineError codes that are the caller's fault (4xx) rather than a genuine
#: "the world offers no answer" state.
_CLIENT_ERROR_CODES = {
    ErrorCode.INVALID_REQUEST,
    ErrorCode.INVALID_EMERGENCY,
    ErrorCode.MISSING_ORIGIN,
    ErrorCode.UNKNOWN_NODE,
    ErrorCode.UNKNOWN_ROAD,
    ErrorCode.UNKNOWN_HOSPITAL,
    ErrorCode.UNSUPPORTED_REQUIREMENT,
    ErrorCode.INVALID_CHAOS_EVENT,
}

#: Codes meaning "the request was valid but no answer exists". The frontend
#: shows these as a dispatcher-facing state, not as a bug.
_NO_SOLUTION_CODES = {
    ErrorCode.NO_ELIGIBLE_HOSPITAL,
    ErrorCode.NO_FEASIBLE_ROUTE,
}


def parse_body(event: Any) -> Dict[str, Any]:
    """Accept an API Gateway proxy event or a direct-invoke dict."""
    if event is None:
        return {}
    if isinstance(event, str):
        return _loads(event)
    if not isinstance(event, dict):
        raise EngineError(
            ErrorCode.INVALID_REQUEST,
            "Request event must be a JSON object.",
            received=type(event).__name__,
        )
    if "body" in event:
        body = event["body"]
        if body is None:
            return {}
        if isinstance(body, str):
            return _loads(body)
        if isinstance(body, dict):
            return body
        raise EngineError(ErrorCode.INVALID_REQUEST, "Request body must be a JSON object.")
    return event


def _loads(raw: str) -> Dict[str, Any]:
    if not raw.strip():
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise EngineError(ErrorCode.INVALID_REQUEST, f"Request body is not valid JSON: {exc.msg}") from exc
    if not isinstance(parsed, dict):
        raise EngineError(ErrorCode.INVALID_REQUEST, "Request body must be a JSON object.")
    return parsed


def status_code_for(error: EngineError) -> int:
    if error.code in _CLIENT_ERROR_CODES:
        return 400
    if error.code in _NO_SOLUTION_CODES:
        return 409  # valid request, but the world offers no feasible answer
    return 500


def api_response(body: Dict[str, Any], status_code: int = 200) -> Dict[str, Any]:
    """API Gateway proxy response. ``body`` is serialised here, once."""
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
        },
        "body": json.dumps(body, default=str),
    }


def handle_engine_error(error: EngineError, request_id: Optional[str] = None) -> Dict[str, Any]:
    return api_response(error_response(error, request_id), status_code_for(error))
