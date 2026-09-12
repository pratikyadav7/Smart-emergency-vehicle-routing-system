"""
Emergency Green-Corridor Planner
Person C deliverable: Routing & Simulation Engine

Owns: road graph, route generation, hospital-route scoring, ambulance
movement simulation, Chaos Mode, and dynamic rerouting.

Deterministic and explainable by design (no ML), per the 8-hour build plan.
Returns plain dict/JSON objects so Person A (frontend) and Person B
(AWS backend) can consume a stable contract:

    {
      "hospital": {...},
      "recommended_route": {...},
      "alternatives": [...],
      "reasons": {...}
    }

Run this file directly for a self-contained demo:
    python3 engine.py
"""

import json
import math
import time
import os
import itertools

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "data")

TRAFFIC_SCORE = {"low": 100, "medium": 65, "high": 30}
CAPACITY_SCORE = {"high": 100, "medium": 65, "low": 35}


def haversine_km(lat1, lon1, lat2, lon2):
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlambda / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


class HistoryLog:
    """Timestamped event log -> feeds the History panel / audit trail."""

    def __init__(self):
        self.events = []
        self._counter = itertools.count(1)

    def add(self, event_type, message, **extra):
        event = {
            "id": f"EVT{next(self._counter):03d}",
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "event_type": event_type,
            "message": message,
        }
        event.update(extra)
        self.events.append(event)
        return event

    def as_list(self):
        return list(self.events)


class RoutingEngine:
    def __init__(self, roads_path=None, hospitals_path=None, history: HistoryLog = None):
        roads_path = roads_path or os.path.join(DATA_DIR, "roads.json")
        hospitals_path = hospitals_path or os.path.join(DATA_DIR, "hospitals.json")

        with open(roads_path) as f:
            road_data = json.load(f)
        with open(hospitals_path) as f:
            hosp_data = json.load(f)

        self.city = road_data.get("city")
        self.nodes = {n["id"]: n for n in road_data["nodes"]}
        self.edges = {e["id"]: e for e in road_data["edges"]}
        self.hospitals = {h["id"]: h for h in hosp_data["hospitals"]}
        self.history = history or HistoryLog()

        # adjacency list, built from edges (roads are bidirectional for this prototype)
        self.adj = {n: [] for n in self.nodes}
        for e in self.edges.values():
            self.adj[e["from"]].append(e)
            self.adj[e["to"]].append({**e, "from": e["to"], "to": e["from"]})

    # ---------------------------------------------------------------
    # Road graph helpers
    # ---------------------------------------------------------------

    def edge_distance_km(self, edge):
        a, b = self.nodes[edge["from"]], self.nodes[edge["to"]]
        return haversine_km(a["lat"], a["lon"], b["lat"], b["lon"])

    def edge_eta_min(self, edge):
        dist = self.edge_distance_km(edge)
        speed = max(edge["speed_kmph"], 5)
        return (dist / speed) * 60

    # ---------------------------------------------------------------
    # Route generation (simple-paths search, capped, closed roads excluded)
    # ---------------------------------------------------------------

    def find_routes(self, origin, destination, max_routes=3, max_hops=6):
        if origin not in self.nodes or destination not in self.nodes:
            return []

        results = []

        def dfs(current, target, path, edges_used, visited):
            if len(results) >= max_routes * 4:  # safety cap on search
                return
            if len(path) - 1 > max_hops:
                return
            if current == target:
                results.append(list(edges_used))
                return
            for edge in self.adj[current]:
                nxt = edge["to"]
                if edge["status"] == "closed":
                    continue
                if nxt in visited:
                    continue
                visited.add(nxt)
                path.append(nxt)
                edges_used.append(edge)
                dfs(nxt, target, path, edges_used, visited)
                path.pop()
                edges_used.pop()
                visited.remove(nxt)

        dfs(origin, destination, [origin], [], {origin})

        # dedupe by node sequence, sort by raw distance, keep shortest few
        seen = set()
        unique = []
        for edges in results:
            seq = tuple(e["id"] for e in edges)
            if seq in seen:
                continue
            seen.add(seq)
            unique.append(edges)

        unique.sort(key=lambda edges: sum(self.edge_distance_km(e) for e in edges))
        return unique[:max_routes]

    # ---------------------------------------------------------------
    # Scoring
    # ---------------------------------------------------------------

    def score_route(self, edges, priority):
        """Score a single route (list of edge dicts). Higher = better."""
        total_dist = sum(self.edge_distance_km(e) for e in edges)
        total_eta = sum(self.edge_eta_min(e) for e in edges)

        traffic_scores = [TRAFFIC_SCORE.get(e["traffic"], 50) for e in edges]
        safety_scores = [e["safety"] for e in edges]
        capacity_scores = [CAPACITY_SCORE.get(e["capacity"], 50) for e in edges]

        avg_traffic = sum(traffic_scores) / len(traffic_scores)
        avg_safety = sum(safety_scores) / len(safety_scores)
        avg_capacity = sum(capacity_scores) / len(capacity_scores)

        # ETA score: shorter is better, normalised against a 30-min ceiling
        eta_score = max(0, 100 - (total_eta / 30) * 100)

        incidents = [e for e in edges if e.get("incident")]
        incident_penalty = sum(e["incident"].get("delay_penalty", 0) for e in incidents)

        # Weights shift with priority (Section 5 of the PDF proposal):
        # high-priority cases weight medical fit / travel time harder;
        # low-priority cases let safety / traffic carry more weight.
        if priority >= 7:
            w = {"eta": 0.40, "traffic": 0.15, "safety": 0.15, "capacity": 0.10}
        elif priority <= 3:
            w = {"eta": 0.25, "traffic": 0.20, "safety": 0.30, "capacity": 0.10}
        else:
            w = {"eta": 0.35, "traffic": 0.15, "safety": 0.20, "capacity": 0.10}

        base = (
            eta_score * w["eta"]
            + avg_traffic * w["traffic"]
            + avg_safety * w["safety"]
            + avg_capacity * w["capacity"]
        )
        score = round(max(0, base - incident_penalty), 1)

        return {
            "distance_km": round(total_dist, 2),
            "eta_min": round(total_eta, 1),
            "avg_traffic_score": round(avg_traffic, 1),
            "avg_safety_score": round(avg_safety, 1),
            "avg_capacity_score": round(avg_capacity, 1),
            "incident_penalty": incident_penalty,
            "score": score,
            "has_incident": bool(incidents),
            "node_path": [edges[0]["from"]] + [e["to"] for e in edges] if edges else [],
            "edge_ids": [e["id"] for e in edges],
        }

    def describe_route(self, node_path):
        names = [self.nodes[n]["name"] for n in node_path]
        return " -> ".join(names)

    # ---------------------------------------------------------------
    # Hospital eligibility
    # ---------------------------------------------------------------

    def eligible_hospitals(self, needs):
        """needs: set of {'icu','trauma','cardiac'} required capabilities."""
        eligible = []
        for h in self.hospitals.values():
            if not h["accepting"] or h["emergency_beds"] <= 0:
                continue
            if "icu" in needs and not h["icu_available"]:
                continue
            if "trauma" in needs and not h["trauma_available"]:
                continue
            if "cardiac" in needs and not h["cardiac_available"]:
                continue
            eligible.append(h)
        return eligible

    # ---------------------------------------------------------------
    # Full recommendation: hospital + route, jointly
    # ---------------------------------------------------------------

    def recommend(self, origin, needs, priority, preferred_hospital_id=None):
        needs = set(needs)
        eligible = self.eligible_hospitals(needs)

        warning = None
        if preferred_hospital_id:
            preferred = self.hospitals.get(preferred_hospital_id)
            if preferred and preferred not in eligible:
                reason_bits = []
                if not preferred["accepting"] or preferred["emergency_beds"] <= 0:
                    reason_bits.append("no emergency capacity")
                if "icu" in needs and not preferred["icu_available"]:
                    reason_bits.append("no ICU")
                if "trauma" in needs and not preferred["trauma_available"]:
                    reason_bits.append("no trauma capability")
                if "cardiac" in needs and not preferred["cardiac_available"]:
                    reason_bits.append("no cardiac capability")
                warning = (
                    f"Preferred hospital {preferred['name']} cannot be used: "
                    f"{', '.join(reason_bits)}."
                )
                self.history.add(
                    "hospital_rejected", warning, hospital_id=preferred_hospital_id
                )

        if not eligible:
            self.history.add("no_feasible_option", "No suitable hospital available for these needs.")
            return {
                "hospital": None,
                "recommended_route": None,
                "alternatives": [],
                "reasons": {"warning": warning, "explanation": "No hospital currently meets the required medical capabilities."},
            }

        candidates = []
        for hosp in eligible:
            routes = self.find_routes(origin, hosp["node"])
            for edges in routes:
                scored = self.score_route(edges, priority)
                # soft preference bonus, applied only after suitability passes
                preference_bonus = 8 if preferred_hospital_id == hosp["id"] else 0
                combined_score = round(scored["score"] + preference_bonus, 1)
                candidates.append({"hospital": hosp, "route": scored, "combined_score": combined_score})

        if not candidates:
            self.history.add("no_route", "No route exists to any suitable hospital.")
            return {
                "hospital": None,
                "recommended_route": None,
                "alternatives": [],
                "reasons": {"warning": warning, "explanation": "No route could be found to a suitable hospital."},
            }

        candidates.sort(key=lambda c: c["combined_score"], reverse=True)
        best = candidates[0]
        alternatives = candidates[1:4]

        reasons = self._build_explanation(best, alternatives, preferred_hospital_id, warning)

        self.history.add(
            "recommendation",
            f"Recommended {best['hospital']['name']} via "
            f"{self.describe_route(best['route']['node_path'])} "
            f"(score {best['combined_score']}, ETA {best['route']['eta_min']} min).",
            hospital_id=best["hospital"]["id"],
        )

        return {
            "hospital": best["hospital"],
            "recommended_route": best["route"],
            "alternatives": [{"hospital": c["hospital"], "route": c["route"], "combined_score": c["combined_score"]} for c in alternatives],
            "reasons": reasons,
        }

    def _build_explanation(self, best, alternatives, preferred_hospital_id, warning):
        why_hospital = (
            f"{best['hospital']['name']} has the required facilities available and is "
            f"currently accepting emergencies."
        )
        why_route = (
            f"ETA {best['route']['eta_min']} min, traffic score {best['route']['avg_traffic_score']}, "
            f"safety score {best['route']['avg_safety_score']}, "
            f"{'an active incident is present' if best['route']['has_incident'] else 'no active incident'}."
        )
        why_not = {}
        for c in alternatives:
            tag = f"{c['hospital']['name']} via {c['route']['edge_ids']}"
            if c["route"]["has_incident"]:
                why_not[tag] = "affected by an active incident."
            elif c["route"]["eta_min"] > best["route"]["eta_min"]:
                why_not[tag] = f"feasible, but slower ({c['route']['eta_min']} min vs {best['route']['eta_min']} min)."
            else:
                why_not[tag] = "feasible, but scored lower overall."

        return {
            "why_this_hospital": why_hospital,
            "why_this_route": why_route,
            "why_not_alternatives": why_not,
            "warning": warning,
        }

    # ---------------------------------------------------------------
    # Chaos Mode
    # ---------------------------------------------------------------

    def inject_accident(self, edge_id, severity="major", delay_penalty=25):
        edge = self.edges[edge_id]
        edge["incident"] = {"type": "accident", "severity": severity, "delay_penalty": delay_penalty}
        edge["traffic"] = "high"
        self.history.add("chaos_accident", f"Accident injected on {edge['name']} ({edge_id}).", edge_id=edge_id)

    def inject_closure(self, edge_id):
        edge = self.edges[edge_id]
        edge["status"] = "closed"
        self.history.add("chaos_closure", f"{edge['name']} ({edge_id}) marked closed.", edge_id=edge_id)

    def inject_traffic_spike(self, edge_id):
        edge = self.edges[edge_id]
        edge["traffic"] = "high"
        self.history.add("chaos_traffic", f"Traffic spike on {edge['name']} ({edge_id}).", edge_id=edge_id)

    def inject_hospital_full(self, hospital_id):
        h = self.hospitals[hospital_id]
        h["emergency_beds"] = 0
        self.history.add("chaos_hospital_full", f"{h['name']} reports 0 emergency beds.", hospital_id=hospital_id)

    def clear_chaos(self, edge_id=None):
        if edge_id:
            self.edges[edge_id].pop("incident", None)

    # ---------------------------------------------------------------
    # Ambulance movement simulation
    # ---------------------------------------------------------------

    def simulate_ambulance(self, ambulance_id, node_path):
        """Produces a timestamped, node-by-node movement log (used to drive
        the Live Map / Green Corridor panel on the frontend)."""
        log = []
        cumulative_min = 0
        for i in range(len(node_path) - 1):
            edge = self._find_edge(node_path[i], node_path[i + 1])
            eta = self.edge_eta_min(edge)
            cumulative_min += eta
            log.append({
                "ambulance_id": ambulance_id,
                "from": self.nodes[node_path[i]]["name"],
                "to": self.nodes[node_path[i + 1]]["name"],
                "segment_eta_min": round(eta, 1),
                "cumulative_eta_min": round(cumulative_min, 1),
                "green_corridor_junction": node_path[i + 1],
                "priority_granted": True,
            })
        self.history.add(
            "ambulance_dispatched",
            f"Ambulance {ambulance_id} en route: {self.describe_route(node_path)}.",
            ambulance_id=ambulance_id,
        )
        return log

    def _find_edge(self, a, b):
        for e in self.adj[a]:
            if e["to"] == b:
                return e
        raise ValueError(f"No edge between {a} and {b}")

    # ---------------------------------------------------------------
    # Reroute (after a Chaos Mode event mid-transit)
    # ---------------------------------------------------------------

    def reroute(self, current_node, destination_node, priority):
        routes = self.find_routes(current_node, destination_node)
        if not routes:
            self.history.add("reroute_failed", "No alternative route available.")
            return None
        scored = [self.score_route(edges, priority) for edges in routes]
        scored.sort(key=lambda s: s["score"], reverse=True)
        best = scored[0]
        self.history.add(
            "reroute_proposed",
            f"New recommended route: {self.describe_route(best['node_path'])} "
            f"(score {best['score']}, ETA {best['eta_min']} min).",
        )
        return {"recommended_route": best, "alternatives": scored[1:3]}
