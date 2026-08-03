# influence_model.py
"""
BGS influence estimation engine.
Formulas derived from community testing (SINC guide, Jane Turner, Taipandot).
"""

from __future__ import annotations
import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional

def _log2(x: float) -> float:
    return math.log2(max(x, 1.0))

def mission_points(inf_str: str) -> float:
    """Map journal Influence string ('+', '++', ...) to points."""
    n = len(inf_str.strip().replace(" ", ""))
    n = max(1, min(n, 5))
    return 0.5 * _log2(n)

def bounty_points(credits: float) -> float:
    return 1.33 * _log2(credits)

def population_factor(population: int) -> float:
    """Effort → influence multiplier. Larger pop → smaller swing."""
    pop = max(int(population), 1000)
    return max(0.025, 1.0 - math.log10(pop) / 10.875)

@dataclass
class Action:
    timestamp: str
    kind: str          # "mission" | "bounty"
    faction: str
    system: str
    raw_value: float   # INF count or credits
    points: float
    est_delta: float   # estimated % contribution of this action

@dataclass
class TrackerState:
    system: str = ""
    faction: str = ""
    population: int = 0
    current_influence: float = 0.0          # 0–1
    actions: List[Action] = field(default_factory=list)
    bucket_counts: Dict[str, int] = field(default_factory=lambda: {"mission": 0, "bounty": 0})
    total_points: float = 0.0
    total_est_delta: float = 0.0

    def add_mission(self, ts: str, system: str, faction: str, inf_str: str) -> Optional[Action]:
        if system != self.system or faction != self.faction:
            return None
        pts = mission_points(inf_str)
        # mild diminishing returns
        self.bucket_counts["mission"] += 1
        decay = 1.0 / (1.0 + 0.15 * math.log1p(self.bucket_counts["mission"]))
        pts *= decay
        delta = pts * population_factor(self.population) * 0.35   # empirical scale → %
        act = Action(ts, "mission", faction, system, len(inf_str), pts, delta)
        self.actions.append(act)
        self.total_points += pts
        self.total_est_delta += delta
        return act

    def add_bounty(self, ts: str, system: str, faction: str, credits: float) -> Optional[Action]:
        if system != self.system or faction != self.faction:
            return None
        pts = bounty_points(credits)
        self.bucket_counts["bounty"] += 1
        decay = 1.0 / (1.0 + 0.12 * math.log1p(self.bucket_counts["bounty"]))
        pts *= decay
        delta = pts * population_factor(self.population) * 0.28
        act = Action(ts, "bounty", faction, system, credits, pts, delta)
        self.actions.append(act)
        self.total_points += pts
        self.total_est_delta += delta
        return act

    def reset_session(self):
        self.actions.clear()
        self.bucket_counts = {"mission": 0, "bounty": 0}
        self.total_points = 0.0
        self.total_est_delta = 0.0