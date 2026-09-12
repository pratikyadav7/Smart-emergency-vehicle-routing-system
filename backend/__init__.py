"""
Emergency Green-Corridor Planner - backend decision & simulation engine.

Public entry points:
    :class:`backend.session.DispatchSession`  - one object per emergency,
        maps 1:1 onto the endpoints in ``docs/api-contract.md``.
    :class:`backend.routing.engine.RoutingEngine` - stateless recommendation
        core, if you only need hospital + route scoring.
"""

from .errors import EngineError, ErrorCode
from .session import DispatchSession

__all__ = ["DispatchSession", "EngineError", "ErrorCode"]
