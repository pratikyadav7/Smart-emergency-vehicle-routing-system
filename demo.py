"""
Mandatory end-to-end demo (Section 18 of the build plan), run on the
Vellore road graph.

Scenario:
  Priority-10 emergency, ICU + Trauma required, originates at Katpadi
  Junction. Dispatcher requests the nearby Vellore Care Multispecialty
  Hospital (H3), which turns out to lack ICU/trauma. The engine selects
  a suitable hospital instead. After dispatcher confirmation and ambulance
  dispatch, Chaos Mode injects an accident on the active route, forcing
  a reroute.

Run: python3 demo.py
"""

import json
from backend.routing.engine import RoutingEngine, HistoryLog


def line(title):
    print("\n" + "=" * 70)
    print(title)
    print("=" * 70)


def show_recommendation(rec):
    if not rec["hospital"]:
        print("No feasible hospital/route:", rec["reasons"]["explanation"])
        return
    h = rec["hospital"]
    r = rec["recommended_route"]
    print(f"RECOMMENDED HOSPITAL: {h['name']}")
    print(f"RECOMMENDED ROUTE:    {engine.describe_route(r['node_path'])}")
    print(f"  ETA {r['eta_min']} min | distance {r['distance_km']} km | score {r['score']}")
    if rec["reasons"]["warning"]:
        print(f"WARNING: {rec['reasons']['warning']}")
    print(f"WHY THIS HOSPITAL? {rec['reasons']['why_this_hospital']}")
    print(f"WHY THIS ROUTE?    {rec['reasons']['why_this_route']}")
    for alt in rec["alternatives"]:
        tag = f"{alt['hospital']['name']} via {alt['route']['edge_ids']}"
        why = rec["reasons"]["why_not_alternatives"].get(tag, "")
        print(f"  Alternative -> {alt['hospital']['name']} "
              f"(ETA {alt['route']['eta_min']} min, score {alt['combined_score']}) - {why}")


if __name__ == "__main__":
    history = HistoryLog()
    engine = RoutingEngine(history=history)

    line("STEP 1-3: Dispatcher creates Priority-10 emergency, requests H3")
    origin = "N1"  # Katpadi Junction
    emergency = {
        "id": "E001",
        "origin": origin,
        "needs": ["icu", "trauma"],
        "priority": 10,
        "preferred_hospital": "H3",  # Vellore Care Multispecialty - lacks ICU/trauma
        "ambulance_id": "A01",
    }
    history.add("emergency_created", "Priority-10 emergency created at Katpadi Junction.", emergency_id="E001")
    print(json.dumps(emergency, indent=2))

    line("STEP 4-7: System checks H3, finds it unsuitable, recommends alternative + shows scores")
    rec = engine.recommend(
        origin=emergency["origin"],
        needs=emergency["needs"],
        priority=emergency["priority"],
        preferred_hospital_id=emergency["preferred_hospital"],
    )
    show_recommendation(rec)

    line("STEP 8-10: Dispatcher confirms dispatch, ambulance starts moving, green corridor activates")
    node_path = rec["recommended_route"]["node_path"]
    movement_log = engine.simulate_ambulance(emergency["ambulance_id"], node_path)
    for m in movement_log:
        print(f"  {m['from']} -> {m['to']}  "
              f"(+{m['segment_eta_min']} min, cumulative {m['cumulative_eta_min']} min)  "
              f"junction {m['green_corridor_junction']}: priority granted")

    line("STEP 11: Dispatcher opens Chaos Mode, injects an accident on the active route")
    active_edge_id = rec["recommended_route"]["edge_ids"][0]
    engine.inject_accident(active_edge_id, severity="major", delay_penalty=30)
    print(f"Accident injected on edge {active_edge_id} ({engine.edges[active_edge_id]['name']}).")

    line("STEP 12-14: System recalculates routes, backup becomes recommended, dispatcher confirms")
    current_node = node_path[0]  # ambulance still near the origin end of the affected edge
    destination_node = rec["hospital"]["node"]
    reroute_result = engine.reroute(current_node, destination_node, emergency["priority"])
    if reroute_result:
        best = reroute_result["recommended_route"]
        print(f"NEW RECOMMENDED ROUTE: {engine.describe_route(best['node_path'])}")
        print(f"  ETA {best['eta_min']} min | score {best['score']} | "
              f"incident on route: {best['has_incident']}")
        for alt in reroute_result["alternatives"]:
            print(f"  Alternative -> {engine.describe_route(alt['node_path'])} "
                  f"(ETA {alt['eta_min']} min, score {alt['score']})")

    line("STEP 15-16: Updated ETA/route shown, full timestamped history")
    print(json.dumps(history.as_list(), indent=2))
