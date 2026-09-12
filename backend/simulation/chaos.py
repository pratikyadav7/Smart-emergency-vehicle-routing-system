"""
Chaos Mode: controlled environmental disruption.

Each event mutates the shared world state (graph or hospital registry) and
nothing else. The routing engine is never told *which* route to pick as a
result - it simply re-runs against the changed world, which is what makes the
reroute demonstration honest rather than scripted.

Supported events:
  ACCIDENT           - attaches an incident (adds real delay minutes) and
                       degrades the road's traffic level.
  ROAD_CLOSURE       - marks the road untraversable; the search skips it.
  TRAFFIC_SPIKE      - raises the traffic level, lowering effective speed.
  HOSPITAL_CAPACITY  - changes beds / accepting status, which feeds straight
                       back into medical eligibility.
"""

from typing import Any, Dict, Optional

from .. import config
from ..errors import EngineError, ErrorCode
from ..history import EventType, HistoryLog
from ..models.hospital import Hospital
from ..models.incident import ChaosEvent, ChaosEventType, Incident
from ..models.road import RoadStatus
from ..routing.graph import RoadGraph


class ChaosController:
    """Applies validated chaos events to the world state."""

    def __init__(
        self,
        graph: RoadGraph,
        hospitals: Dict[str, Hospital],
        history: Optional[HistoryLog] = None,
    ) -> None:
        self.graph = graph
        self.hospitals = hospitals
        self.history = history if history is not None else HistoryLog()
        self.applied: list = []

    # -- entry point ---------------------------------------------------

    def inject(self, raw_event: Any) -> Dict[str, Any]:
        """Validate and apply one chaos event. Returns a JSON-safe summary."""
        event = raw_event if isinstance(raw_event, ChaosEvent) else ChaosEvent.from_dict(raw_event)

        handlers = {
            ChaosEventType.ACCIDENT: self._accident,
            ChaosEventType.ROAD_CLOSURE: self._closure,
            ChaosEventType.TRAFFIC_SPIKE: self._traffic_spike,
            ChaosEventType.HOSPITAL_CAPACITY: self._hospital_capacity,
        }
        summary = handlers[event.type](event)

        self.applied.append(summary)
        self.history.add(
            EventType.CHAOS_INJECTED,
            summary["message"],
            chaos_type=event.type,
            road_id=event.road_id,
            hospital_id=event.hospital_id,
        )
        return summary

    # -- individual events ---------------------------------------------

    def _road(self, event: ChaosEvent):
        try:
            return self.graph.road(event.road_id)
        except EngineError as exc:
            raise EngineError(
                ErrorCode.INVALID_CHAOS_EVENT,
                f"Chaos event references unknown road {event.road_id!r}.",
                road_id=event.road_id,
            ) from exc

    def _accident(self, event: ChaosEvent) -> Dict[str, Any]:
        road = self._road(event)
        incident = Incident(
            type="accident",
            severity=event.severity,
            description=event.description or f"Accident reported on {road.name}.",
        )
        road.incident = incident
        previous_traffic = road.traffic
        road.traffic = config.INCIDENT_TRAFFIC_LEVEL
        return {
            "type": event.type,
            "road_id": road.id,
            "road_name": road.name,
            "severity": event.severity,
            "added_delay_minutes": incident.delay_minutes,
            "traffic": {"before": previous_traffic, "after": road.traffic},
            "message": (
                f"{event.severity.capitalize()} accident on {road.name} ({road.id}): "
                f"+{incident.delay_minutes} min delay, traffic now {road.traffic}."
            ),
        }

    def _closure(self, event: ChaosEvent) -> Dict[str, Any]:
        road = self._road(event)
        road.status = RoadStatus.CLOSED
        return {
            "type": event.type,
            "road_id": road.id,
            "road_name": road.name,
            "status": road.status,
            "message": f"{road.name} ({road.id}) is closed to all traffic.",
        }

    def _traffic_spike(self, event: ChaosEvent) -> Dict[str, Any]:
        road = self._road(event)
        previous = road.traffic
        self.graph.set_traffic(road.id, config.TRAFFIC_SPIKE_LEVEL)
        return {
            "type": event.type,
            "road_id": road.id,
            "road_name": road.name,
            "traffic": {"before": previous, "after": road.traffic},
            "message": (
                f"Traffic on {road.name} ({road.id}) surged from {previous} to {road.traffic}."
            ),
        }

    def _hospital_capacity(self, event: ChaosEvent) -> Dict[str, Any]:
        hospital = self.hospitals.get(event.hospital_id)
        if hospital is None:
            raise EngineError(
                ErrorCode.INVALID_CHAOS_EVENT,
                f"Chaos event references unknown hospital {event.hospital_id!r}.",
                hospital_id=event.hospital_id,
            )

        before = {"emergency_beds": hospital.emergency_beds, "accepting": hospital.accepting}
        # Default behaviour with no explicit values: the hospital goes full.
        hospital.emergency_beds = (
            event.emergency_beds if event.emergency_beds is not None else 0
        )
        if event.accepting is not None:
            hospital.accepting = event.accepting
        elif hospital.emergency_beds == 0:
            hospital.accepting = False

        return {
            "type": event.type,
            "hospital_id": hospital.id,
            "hospital_name": hospital.name,
            "before": before,
            "after": {
                "emergency_beds": hospital.emergency_beds,
                "accepting": hospital.accepting,
            },
            "message": (
                f"{hospital.name} now reports {hospital.emergency_beds} emergency bed(s) "
                f"and is {'accepting' if hospital.accepting else 'not accepting'} patients."
            ),
        }

    # -- introspection --------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        return {
            "events_applied": list(self.applied),
            "closed_roads": self.graph.closed_roads(),
            "active_incidents": self.graph.active_incidents(),
        }
