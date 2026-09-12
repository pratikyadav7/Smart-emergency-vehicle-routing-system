# Smart Emergency Vehicle Routing System

Emergency Green-Corridor Planner - a dispatcher-centric simulation of
emergency vehicle routing for the city of Vellore.

A dispatcher receives an emergency, the system finds a medically suitable
hospital, scores several candidate routes, recommends one with a full
explanation, simulates the ambulance and its green corridor, and recalculates
when Chaos Mode disrupts the world mid-transit.

> This is a simulation-first prototype. The green corridor is **simulated
> signal priority only** - nothing in this system contacts or controls real
> traffic infrastructure, and hospital availability figures are synthetic.

## Quick start

No dependencies beyond the Python standard library (3.9+).

```bash
python3 demo.py                 # the full scripted demo scenario
pytest tests/ -q                # the test suite (pytest is the only dev dep)
```

`demo_run_output.txt` is a checked-in transcript of `demo.py`.

## Repository layout

```
backend/
├── config.py                 every tunable constant and scoring weight
├── errors.py                 machine-readable failure states
├── history.py                the decision/audit log
├── session.py                DispatchSession - one object per emergency
├── models/                   Node, Road, Hospital, Emergency, Incident, state
├── routing/
│   ├── graph.py              road graph + travel-time cost model
│   ├── algorithms.py         Dijkstra, A*, alternative-route generation
│   ├── hospitals.py          medical eligibility gate
│   ├── scoring.py            eight-component explainable score
│   ├── explanations.py       dispatcher-facing reasons
│   └── engine.py             the recommendation engine (/analyze, /reroute)
├── simulation/
│   ├── ambulance.py          node-by-node movement
│   ├── corridor.py           simulated green corridor
│   └── chaos.py              Chaos Mode events
└── lambda_handlers/          AWS Lambda entry points for /analyze and /reroute
data/
├── roads.json                the synthetic Vellore road graph
├── hospitals.json            hospital capabilities and capacity
└── scenarios/                the scripted demo scenario
docs/api-contract.md          authoritative request/response schemas
tests/                        unit + end-to-end tests
```

## How it works

**Road graph.** Roads are bidirectional edges carrying speed, traffic level,
capacity, safety and status. Travel time is derived, never stored:

```
effective_speed = speed_kmph * traffic_factor      (low 1.0, medium 0.75, high 0.45)
travel_time_min = distance_km / effective_speed * 60 + incident_delay
```

So a traffic spike or an accident changes the actual ETA, not just a score. A
road marked `closed` is never traversed.

**Hospital eligibility comes before preference.** ICU, trauma and cardiac
requirements, accepting status and bed capacity are a hard gate. A dispatcher
cannot route an ICU patient to a facility without ICU, however close it is or
however explicitly it was requested - the preferred hospital is only a
tie-break among hospitals that already passed.

**Dijkstra for the candidate landscape, A\* for the chosen path.** One
Dijkstra sweep prices every hospital in the network at once, which is what
shortlisting needs. A\* then computes the actual path to each shortlisted
destination, guided by straight-line distance at the network's top speed - an
admissible heuristic, so A\* returns the same optimal cost as Dijkstra while
expanding fewer nodes. The test suite asserts that equality on both graphs.

**Alternatives are real.** Up to three routes come from a deterministic
road-removal search (the first level of Yen's algorithm): take the optimal
path, then re-plan with each of its roads removed. If the graph only supports
one route, one route is returned. Routes are never synthesised.

**Scoring is multi-factor and fully visible.** Eight components, each
normalised 0-100 with higher always better, combined with priority-dependent
weights that sum to 1.0:

```
medical_fit · hospital_readiness · travel_time · traffic
road_capacity · safety · incident_penalty · priority_preference
```

Every response carries the components, the weights and the per-component
contributions, and `total` is exactly their sum. All the constants live in
`backend/config.py`. Selection is genuinely multi-factor: a safer route can
and does beat a faster one under a low-priority profile.

**Chaos Mode changes the world, not the answer.** `ACCIDENT`, `ROAD_CLOSURE`,
`TRAFFIC_SPIKE` and `HOSPITAL_CAPACITY` mutate the graph or the hospital
registry and nothing else. Rerouting re-runs the same pipeline from the
ambulance's current node against the changed state - there is no
"if accident then take route 3" anywhere in the code, and the tests prove the
decision follows the graph.

## Integration

`backend.session.DispatchSession` maps one method per endpoint; see
[`docs/api-contract.md`](docs/api-contract.md) for the full schemas.
`/analyze` and `/reroute` also ship as AWS Lambda handlers under
`backend/lambda_handlers/`. Everything crossing the boundary is a plain
JSON-safe dict - no Python objects leak into API responses.

`lambda_handlers` is spelled out rather than `lambda` because `lambda` is a
Python keyword and a package by that name cannot be imported or unit-tested.
Deployment is unaffected: point each function at
`backend.lambda_handlers.analyze.handler.handler`.
