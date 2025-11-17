# ============================
# IV (Routing Core & Failure Handling)
# ============================

from __future__ import annotations
from typing import Dict, Tuple, List, Optional
import math
import time

INF: float = math.inf

# Identity & timing (set by init_core)
_self_id: Optional[int] = None
_update_interval: Optional[int] = None  # seconds

# Direct link costs FROM self to neighbors
# direct[self][n] = cost
direct: Dict[int, Dict[int, float]] = {}

# Distance vector state for this server:
# routing_table[dest] = (next_hop, total_cost)
routing_table: Dict[int, Tuple[int, float]] = {}

# Neighbor heartbeat timestamps (last time we heard an update from that neighbor)
last_heard: Dict[int, float] = {}

# Packets counter (increment on valid neighbor update; reset on getter)
_packets_since_last_read: int = 0

neighbor_vectors: Dict[int, Dict[int, float]] = {}


# ---------- Initialization ----------
def init_core(self_id: int, all_server_ids: List[int],
              neighbor_costs: Dict[int, float],
              update_interval: int) -> None:
    """
    Initialize Role-B core.
    - self_id: this server's ID
    - all_server_ids: list of all server IDs in the network
    - neighbor_costs: direct costs from self to each neighbor {neighbor_id: cost}
    - update_interval: seconds between periodic updates (needed for 3-interval failure rule)
    """
    global _self_id, _update_interval, direct, routing_table, last_heard, _packets_since_last_read
    _self_id = self_id
    _update_interval = update_interval
    _packets_since_last_read = 0

    direct = {self_id: {}}
    for n in neighbor_costs:
        direct[self_id][n] = float(neighbor_costs[n])

    routing_table = {}
    for d in all_server_ids:
        if d == self_id:
            routing_table[d] = (self_id, 0.0)
        elif d in direct[self_id]:
            routing_table[d] = (d, float(direct[self_id][d]))
        else:
            routing_table[d] = (_self_id, INF)

    last_heard = {}


# ---------- Public API (called by A & C) ----------

def apply_neighbor_vector(from_id: int, neighbor_vector: Dict[int, float]) -> None:
    global _packets_since_last_read
    _require_init()
    note_heartbeat(from_id)

    # ignore updates from non-neighbors
    if from_id not in direct[_self_id]:
        return

    neighbor_vectors[from_id] = {int(d): float(c) for d, c in neighbor_vector.items()}

    _recompute_all()
    _packets_since_last_read += 1


def set_direct_cost(u: int, v: int, cost: float) -> None:
    """
    Handles 'update' and 'disable' semantics for links that involve self.
    This project’s costs are bi-directional; we store only self's row and assume symmetry.
    If the change involves self, update our direct cost and recompute routes.
    """
    _require_init()
    if _self_id not in (u, v):
        return  # change does not involve us; nothing to do in this process

    n = v if u == _self_id else u
    direct[_self_id][n] = float(cost)
    _recompute_all()


def crash_all() -> None:
    """
    Simulate a crash from our side: set all direct links to ∞ and recompute.
    (Neighbors will eventually mark us ∞ after missing 3 intervals.)
    """
    _require_init()
    for n in list(direct[_self_id].keys()):
        direct[_self_id][n] = INF
    _recompute_all()


def snapshot() -> List[Tuple[int, int, float]]:
    """
    Return a list of (dest, next_hop, cost), sorted by dest ID.
    C will print in the exact format required by the spec.
    """
    _require_init()
    return sorted(
        [(d, routing_table[d][0], routing_table[d][1]) for d in routing_table],
        key=lambda x: x[0],
    )


def get_and_reset_packets() -> int:
    """
    Return number of distance-vector packets processed since last call, then reset.
    (C will print and reset per 'packets' command.)
    """
    global _packets_since_last_read
    _require_init()
    x = _packets_since_last_read
    _packets_since_last_read = 0
    return x


def note_heartbeat(from_id: int) -> None:
    """Record that a neighbor sent us something in the current time window."""
    _require_init()
    last_heard[from_id] = time.time()


def expire_silent_neighbors(now: Optional[float] = None) -> None:
    """
    Enforce the '3 intervals' failure rule: if we haven't heard from a neighbor
    for >= 3 * update_interval, set that direct link to ∞ and recompute.
    """
    _require_init()
    if now is None:
        now = time.time()
    threshold = 3 * _update_interval
    changed = False
    for n, t in list(last_heard.items()):
        if n in direct[_self_id] and direct[_self_id][n] < INF:
            if now - t >= threshold:  # missed three consecutive updates
                direct[_self_id][n] = INF
                changed = True
    if changed:
        _recompute_all()


# ---------- Internal helpers ----------

def _recompute_all() -> None:
    """Recompute routing_table using direct links + last-known neighbor vectors."""
    global routing_table
    new_table: Dict[int, Tuple[int, float]] = {}

    all_dests = set(routing_table.keys()) if routing_table else set()
    all_dests.add(_self_id)
    for n in direct[_self_id]:
        all_dests.add(n)
    for vec in neighbor_vectors.values():
        all_dests.update(vec.keys())

    for d in all_dests:
        if d == _self_id:
            new_table[d] = (_self_id, 0.0)
            continue

        # *** NEW LOGIC: if d is a direct neighbor whose link has been set to INF
        # (by expire_silent_neighbors after a crash/timeout), then we must treat
        # that destination as completely unreachable from this router, regardless
        # of what other neighbors claim. This prevents count-to-infinity and
        # matches the spec's "neighbor no longer exists in the network" wording.
        if d in direct[_self_id] and direct[_self_id][d] >= INF:
            new_table[d] = (_self_id, INF)
            continue

        best_cost = direct[_self_id].get(d, INF)
        best_nh = d if best_cost < INF else _self_id

        for k, cost_self_k in direct[_self_id].items():
            if cost_self_k >= INF:
                continue
            k_vec = neighbor_vectors.get(k, {})
            k_to_d = k_vec.get(d, INF)
            cand = cost_self_k + k_to_d
            if cand < best_cost - 1e-9 or (abs(cand - best_cost) < 1e-9 and k < best_nh):
                best_cost = cand
                best_nh = k

        new_table[d] = (best_nh, float(best_cost))

    routing_table = new_table


def _require_init() -> None:
    if _self_id is None or _update_interval is None:
        raise RuntimeError("routing_core not initialized. Call init_core(...) first.")
