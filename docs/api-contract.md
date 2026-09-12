# Emergency Green Corridor API Contract

Version: 1.1

This document defines the API interface between the frontend,
AWS backend, and routing/simulation engine.

Version 1.1 adds the request/response schemas for the routing and simulation
engine (Person C). The endpoint list from 1.0 is unchanged.

## Endpoints

- POST /emergencies
- POST /analyze
- POST /dispatch/confirm
- GET /state
- POST /chaos/inject
- POST /reroute
- POST /reroute/confirm
- GET /history

## Engine entry points

The engine is a plain Python package with no framework or AWS dependency.
Person B wires each endpoint to one method:

| Endpoint              | Engine call                              |
| --------------------- | ---------------------------------------- |
| POST /emergencies     | `DispatchSession.create_emergency(body)` |
| POST /analyze         | `DispatchSession.analyze(body)`          |
| POST /dispatch/confirm| `DispatchSession.confirm_dispatch(route_id)` |
| GET  /state           | `DispatchSession.state()`                |
| POST /chaos/inject    | `DispatchSession.inject_chaos(body)`     |
| POST /reroute         | `DispatchSession.reroute(body)`          |
| POST /reroute/confirm | `DispatchSession.confirm_reroute(route_id)` |
| GET  /history         | `DispatchSession.history_events()`       |

Two endpoints also ship as ready-made Lambda handlers that accept an API
Gateway proxy event (or a direct-invoke dict) and return a proxy response:

- `backend.lambda_handlers.analyze.handler.handler`
- `backend.lambda_handlers.reroute.handler.handler`

Lambdas are stateless, so the caller passes the accumulated Chaos Mode events
back in under `environment.chaos_events`; the engine replays them to rebuild
the same world before answering. Replaying the same events always produces the
same recommendation.

## Shared objects

### Emergency

```json
{
  "id": "E001",
  "origin_node": "N2",
  "priority": 10,
  "requirements": ["icu", "trauma"],
  "preferred_hospital_id": "H1",
  "ambulance_id": "A01",
  "description": "Road traffic accident, unconscious patient."
}
```

- `priority` is an integer 1-10 and selects the scoring weight profile
  (`critical` >= 8, `routine` <= 3, `urgent` otherwise).
- `requirements` accepts only `icu`, `trauma`, `cardiac`. Anything else is a
  `400 UNSUPPORTED_REQUIREMENT` - the engine will not guess.
- `preferred_hospital_id` is a **soft** preference applied only after medical
  eligibility. Legacy keys `origin`, `needs` and `preferred_hospital` are also
  accepted.

### Route

Every route in every response has this shape:

```json
{
  "route_id": "R-H2-1",
  "hospital_id": "H2",
  "hospital_name": "Government Vellore Medical College Hospital",
  "nodes": ["N2", "N1", "N9"],
  "node_names": ["VIT Vellore Gate", "Katpadi Junction", "Govt. Medical College"],
  "edges": ["R2", "R10"],
  "distance_km": 5.37,
  "eta_minutes": 11.58,
  "traffic_condition": "high",
  "traffic_score": 71.16,
  "capacity_score": 100.0,
  "safety_score": 77.35,
  "clear_road_score": 100.0,
  "incident_delay_minutes": 0.0,
  "incident_impact": [],
  "score": 72.31,
  "score_breakdown": { "...": "see below" },
  "recommended": true
}
```

`incident_impact` is a list of
`{road_id, road_name, type, severity, delay_minutes}`.

### Score breakdown

`total` always equals the sum of `contributions`, and each contribution is
`components[k] * weights[k]`. Weights sum to 1.0, so `total` is a 0-100 number.

```json
{
  "total": 72.31,
  "profile": "critical",
  "components": {
    "medical_fit": 90.0, "hospital_readiness": 50.0, "travel_time": 61.4,
    "traffic": 71.16, "road_capacity": 100.0, "safety": 77.35,
    "incident_penalty": 100.0, "priority_preference": 50.0
  },
  "weights": { "...": "same eight keys" },
  "contributions": { "...": "same eight keys" }
}
```

Every component is 0-100 and **higher is better**, including
`incident_penalty`, which measures how clear the roads are (100 = no
incidents).

### Hospital

```json
{
  "id": "H2", "name": "...", "node": "N9", "emergency_beds": 4,
  "icu_available": true, "trauma_available": true, "cardiac_available": false,
  "accepting": true, "capabilities": ["icu", "trauma"]
}
```

## POST /analyze

Request:

```json
{
  "emergency": { "...Emergency..." },
  "environment": { "chaos_events": [ "...ChaosEvent..." ] }
}
```

Response `200`:

```json
{
  "status": "ok",
  "emergency": { "...Emergency..." },
  "origin_node": "N2",
  "hospital": { "...Hospital..." },
  "recommended_route": { "...Route..." },
  "alternatives": [ "...Route..." ],
  "routes": [ "recommended first, then alternatives, ranked by score" ],
  "eligibility": {
    "eligible_hospitals": [ "...Hospital..." ],
    "rejected_hospitals": [
      {"hospital_id": "H1", "hospital_name": "...", "reason": "NOT_ACCEPTING",
       "detail": "human-readable sentence"}
    ],
    "preferred_hospital_used": false
  },
  "reasons": {
    "why_this_hospital": "...",
    "why_this_route": "...",
    "why_not_alternatives": {"R-H2-2": "..."},
    "rejected_hospitals": ["...", "..."],
    "warning": "Requested hospital ... was not used: ..."
  },
  "environment": {"closed_roads": [], "active_incidents": []},
  "history": [ "...HistoryEvent..." ]
}
```

`routes` contains up to three genuinely distinct routes. If the graph supports
fewer, fewer are returned - routes are never fabricated. Exactly one route has
`"recommended": true`.

## POST /reroute

Request:

```json
{
  "emergency": { "...Emergency..." },
  "ambulance": {"current_node": "N1", "ambulance_id": "A01"},
  "current_route": { "...the Route the ambulance is following..." },
  "environment": {"chaos_events": [ "...ChaosEvent..." ]},
  "trigger": {"type": "ACCIDENT", "road_id": "R10", "severity": "major"}
}
```

Response `200`:

```json
{
  "status": "ok",
  "rerouted": true,
  "destination_changed": false,
  "from_node": "N1",
  "old_route": { "...remaining leg of the previous plan, re-priced..." },
  "new_route": { "...Route..." },
  "recommended_route": { "...same as new_route..." },
  "alternatives": [ "...Route..." ],
  "hospital": { "...Hospital..." },
  "old_eta_minutes": 24.35,
  "new_eta_minutes": 15.74,
  "eta_delta_minutes": -8.61,
  "trigger": { "...echoed..." },
  "changed_conditions": {"closed_roads": [], "active_incidents": [ ... ]},
  "reasons": {"why_reroute": "...", "why_this_hospital": "...",
              "why_this_route": "...", "why_not_alternatives": { ... }}
}
```

`old_route` is the **remaining leg** of the previous plan from `current_node`,
re-priced under current conditions, so `old_eta_minutes` and
`new_eta_minutes` are directly comparable. If a road on it has closed,
`old_route.feasible` is `false` and `old_route.eta_minutes` is `null`.

## POST /chaos/inject

```json
{"type": "ACCIDENT", "road_id": "R10", "severity": "major", "description": "..."}
{"type": "ROAD_CLOSURE", "road_id": "R10"}
{"type": "TRAFFIC_SPIKE", "road_id": "R10"}
{"type": "HOSPITAL_CAPACITY", "hospital_id": "H1", "emergency_beds": 0, "accepting": false}
```

`severity` is `minor` | `moderate` | `major` and controls the real delay added
to the road (4 / 8 / 15 minutes). `HOSPITAL_CAPACITY` with no explicit values
sends the hospital to zero beds and not-accepting. `edge_id` is accepted as an
alias for `road_id`.

Response:

```json
{
  "status": "ok",
  "event": {"type": "...", "message": "human-readable", "...": "..."},
  "affects_active_route": true,
  "reroute_recommended": true,
  "environment": {"events_applied": [...], "closed_roads": [], "active_incidents": []}
}
```

## GET /state

```json
{
  "status": "ok",
  "emergency": { "...Emergency..." } ,
  "ambulance": {
    "ambulance_id": "A01", "status": "EN_ROUTE", "current_node": "N1",
    "next_junction": "N9", "destination_node": "N9", "route": ["N1", "N9"],
    "remaining_route": ["N1", "N9"], "current_route_index": 0, "step": 1,
    "elapsed_min": 7.37, "remaining_eta_min": 4.21, "total_eta_min": 11.58,
    "reroute_count": 0, "arrived": false
  },
  "green_corridor": {
    "active": true, "simulated": true,
    "note": "Simulated signal priority. No real traffic infrastructure is controlled.",
    "junctions": [{"node_id": "N1", "node_name": "...", "state": "PRIORITY_GRANTED",
                   "granted_at_step": 0, "priority_granted": true}],
    "priority_nodes": ["N1", "N9"]
  },
  "active_route": { "...Route..." },
  "environment": { ... },
  "hospitals": [ "...Hospital..." ]
}
```

Ambulance `status` is `IDLE` | `EN_ROUTE` | `REROUTING` | `ARRIVED` | `BLOCKED`.
Junction `state` is `NORMAL` | `PRIORITY_GRANTED` | `CLEARED`.

**The green corridor is simulated only.** No real traffic infrastructure is
contacted or controlled anywhere in this system.

## GET /history

```json
{"status": "ok", "events": [
  {"id": "EVT001", "timestamp": "2026-09-12T19:18:32Z",
   "event_type": "recommendation", "message": "Recommended ...",
   "hospital_id": "H2", "route_id": "R-H2-1"}
]}
```

Event types: `emergency_created`, `hospital_rejected`, `recommendation`,
`no_feasible_option`, `dispatch_confirmed`, `ambulance_moved`,
`corridor_granted`, `corridor_released`, `arrived`, `chaos_injected`,
`reroute_proposed`, `reroute_confirmed`, `reroute_failed`.

`id`, `timestamp`, `event_type` and `message` are always present; other keys
vary by event type.

## Errors

The engine never returns fabricated data. When no real answer exists it
returns an error envelope:

```json
{"status": "error", "error": {"code": "NO_ELIGIBLE_HOSPITAL",
                              "message": "human-readable",
                              "details": { "...optional..." }}}
```

| Code | HTTP | Meaning |
| ---- | ---- | ------- |
| `INVALID_REQUEST` | 400 | Malformed body, or an out-of-sequence call |
| `INVALID_EMERGENCY` | 400 | Emergency payload failed validation |
| `MISSING_ORIGIN` | 400 | No origin node supplied |
| `UNKNOWN_NODE` | 400 | Node is not in the road network |
| `UNKNOWN_ROAD` | 400 | Road id is not in the road network |
| `UNKNOWN_HOSPITAL` | 400 | Preferred hospital does not exist |
| `UNSUPPORTED_REQUIREMENT` | 400 | Medical requirement outside icu/trauma/cardiac |
| `INVALID_CHAOS_EVENT` | 400 | Unknown chaos type, severity, or missing target |
| `NO_ELIGIBLE_HOSPITAL` | 409 | No hospital meets the medical requirements |
| `NO_FEASIBLE_ROUTE` | 409 | No open route to any suitable hospital |
| `SIMULATION_NOT_STARTED` | 500 | Movement requested before dispatch |

`400` means the caller must fix the request. `409` means the request was valid
but the world currently offers no answer - a dispatcher-facing state, not a bug.
