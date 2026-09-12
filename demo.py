"""
Mandatory end-to-end demo for the Emergency Green-Corridor Planner.

Runs the scripted judging scenario from ``data/scenarios/mandatory_demo.json``
against the real engine - every number printed below is computed, not staged.

    python3 demo.py

Scenario: a Priority-10 patient needing ICU + trauma care is picked up at the
VIT Vellore Gate. The dispatcher asks for CMC Vellore (H1), but H1 is on
diversion, so medical eligibility rules it out and a suitable hospital is
chosen instead. After dispatch the ambulance clears one junction, Chaos Mode
puts a major accident on the road ahead, and the engine recalculates a backup
route from the ambulance's current position.
"""

import json
import os
from typing import Any, Dict

from backend.session import DispatchSession

SCENARIO_PATH = os.path.join(os.path.dirname(__file__), "data", "scenarios", "mandatory_demo.json")

BAR = "=" * 78


def step(number: str, title: str) -> None:
    print(f"\n{BAR}\n STEP {number}: {title}\n{BAR}")


def show_route(route: Dict[str, Any], indent: str = "  ") -> None:
    marker = "RECOMMENDED" if route.get("recommended") else "alternative"
    print(f"{indent}[{marker}] {route['route_id']} -> {route['hospital_name']}")
    print(f"{indent}  path      : {' -> '.join(route['node_names'])}")
    print(f"{indent}  roads     : {', '.join(route['edges'])}")
    print(f"{indent}  ETA       : {route['eta_minutes']} min over {route['distance_km']} km")
    print(f"{indent}  conditions: traffic {route['traffic_condition']}, "
          f"safety {route['safety_score']}, capacity {route['capacity_score']}")
    if route["incident_impact"]:
        for incident in route["incident_impact"]:
            print(f"{indent}  incident  : {incident['severity']} {incident['type']} on "
                  f"{incident['road_name']} (+{incident['delay_minutes']} min)")
    print(f"{indent}  SCORE     : {route['score']}")


def show_breakdown(route: Dict[str, Any]) -> None:
    breakdown = route["score_breakdown"]
    print(f"  Score breakdown for {route['route_id']} "
          f"(weight profile: {breakdown['profile']}, total {breakdown['total']}):")
    print(f"    {'component':<22}{'value':>8}{'weight':>9}{'contribution':>14}")
    for key, value in breakdown["components"].items():
        print(f"    {key:<22}{value:>8}{breakdown['weights'][key]:>9}"
              f"{breakdown['contributions'][key]:>14}")


def main() -> None:
    with open(SCENARIO_PATH, encoding="utf-8") as handle:
        scenario = json.load(handle)

    session = DispatchSession()

    step("0", "Simulation world set up (pre-existing hospital status)")
    for event in scenario["setup_events"]:
        result = session.inject_chaos(event)
        print(f"  {result['event']['message']}")

    # ------------------------------------------------------------------
    step("1-3", "Dispatcher creates a Priority-10 emergency and requests H1")
    created = session.create_emergency(scenario["emergency"])
    print(json.dumps(created["emergency"], indent=2))

    # ------------------------------------------------------------------
    step("4-5", "Medical eligibility is evaluated BEFORE preference")
    analysis = session.analyze()
    for rejected in analysis["eligibility"]["rejected_hospitals"]:
        print(f"  REJECTED {rejected['hospital_id']}: {rejected['detail']}")
    for hospital in analysis["eligibility"]["eligible_hospitals"]:
        print(f"  ELIGIBLE {hospital['id']}: {hospital['name']} "
              f"(beds {hospital['emergency_beds']}, capabilities {', '.join(hospital['capabilities'])})")
    print(f"\n  WARNING: {analysis['reasons']['warning']}")

    # ------------------------------------------------------------------
    step("6-7", "Candidate routes, scores and the recommendation")
    print(f"  Selected hospital: {analysis['hospital']['name']} "
          f"({analysis['hospital']['id']}) at {analysis['hospital']['node']}\n")
    for route in analysis["routes"]:
        show_route(route)
        print()
    show_breakdown(analysis["recommended_route"])
    print(f"\n  WHY THIS HOSPITAL: {analysis['reasons']['why_this_hospital']}")
    print(f"  WHY THIS ROUTE   : {analysis['reasons']['why_this_route']}")
    for route_id, reason in analysis["reasons"]["why_not_alternatives"].items():
        print(f"  WHY NOT {route_id}  : {reason}")

    # ------------------------------------------------------------------
    step("8-10", "Dispatcher confirms dispatch; ambulance starts; green corridor activates")
    confirmed = session.confirm_dispatch()
    ambulance = confirmed["ambulance"]
    print(f"  Ambulance {ambulance['ambulance_id']} status {ambulance['status']}, "
          f"total ETA {ambulance['total_eta_min']} min")
    print(f"  Route: {' -> '.join(confirmed['confirmed_route']['node_names'])}")
    print("  Green corridor (SIMULATED - no real traffic infrastructure is controlled):")
    for junction in confirmed["green_corridor"]["junctions"]:
        print(f"    {junction['node_id']:<4} {junction['node_name']:<34} {junction['state']}")

    moved = session.advance(scenario["advance_steps_before_chaos"])
    for movement in moved["movements"]:
        print(f"\n  MOVE: {movement['from_name']} -> {movement['to_name']} via "
              f"{movement['road_name']} (+{movement['segment_minutes']} min)")
    print(f"  Ambulance now at {moved['ambulance']['current_node']}, "
          f"next junction {moved['ambulance']['next_junction']}, "
          f"{moved['ambulance']['remaining_eta_min']} min remaining")
    for junction in moved["green_corridor"]["junctions"]:
        print(f"    {junction['node_id']:<4} {junction['node_name']:<34} {junction['state']}")

    # ------------------------------------------------------------------
    step("11", "CHAOS MODE: accident injected on the active route")
    chaos = session.inject_chaos(scenario["chaos_event"])
    print(f"  {chaos['event']['message']}")
    print(f"  Affects the active route: {chaos['affects_active_route']}")

    # ------------------------------------------------------------------
    step("12-13", "Engine recalculates from the ambulance's current position")
    reroute = session.reroute()
    old_route = reroute["old_route"]
    print(f"  Previous plan (remaining leg): {' -> '.join(old_route['node_names'])} "
          f"= {old_route['eta_minutes']} min")
    print("  New recommendation:")
    show_route(reroute["new_route"], indent="    ")
    print("\n  Alternatives still available:")
    for alternative in reroute["alternatives"]:
        print(f"    {alternative['route_id']}: {' -> '.join(alternative['node_names'])} "
              f"({alternative['eta_minutes']} min, score {alternative['score']})")
    print(f"\n  WHY REROUTE: {reroute['reasons']['why_reroute']}")
    print(f"  ETA change : {reroute['old_eta_minutes']} min -> "
          f"{reroute['new_eta_minutes']} min ({reroute['eta_delta_minutes']:+} min)")

    # ------------------------------------------------------------------
    step("14-15", "Dispatcher confirms the reroute; updated ETA and corridor")
    reconfirmed = session.confirm_reroute()
    print(f"  Confirmed: {' -> '.join(reconfirmed['confirmed_route']['node_names'])}")
    print(f"  Updated ETA: {reconfirmed['updated_eta_minutes']} min")
    for junction in reconfirmed["green_corridor"]["junctions"]:
        print(f"    {junction['node_id']:<4} {junction['node_name']:<34} {junction['state']}")

    print("\n  Completing the journey:")
    while True:
        tick = session.advance(1)
        movement = tick["movements"][0]
        if not movement["moved"]:
            break
        print(f"    {movement['from_name']} -> {movement['to_name']} "
              f"(+{movement['segment_minutes']} min, "
              f"{movement['remaining_eta_min']} min remaining)")
        if movement["arrived"]:
            break
    final = session.state()
    print(f"  Ambulance status: {final['ambulance']['status']} at "
          f"{final['ambulance']['current_node']} after "
          f"{final['ambulance']['elapsed_min']} min")

    # ------------------------------------------------------------------
    step("16", "History: the full decision trail (GET /history)")
    for event in session.history_events()["events"]:
        print(f"  {event['id']}  {event['event_type']:<20} {event['message']}")


if __name__ == "__main__":
    main()
