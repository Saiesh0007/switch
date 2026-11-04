"""A company's private negotiating authority, and the rules that apply it.

Only Counsel imports this module. It contains no AI: limits are compared by plain code, so there
is no model holding a limit that a clever message could talk out of it.

Each clause defines a ladder of positions, best first, and two boundaries:
  auto_through     Counsel may settle or offer up to here without asking anyone.
  signoff_through  The General Counsel may authorise up to here. Beyond it, Counsel holds.

Counters come only from the company's own ladder, never from the other side's number, so a
probing offer learns nothing about where the boundaries sit.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .clauses import CLAUSES, parse_value

ACCEPT = "ACCEPT"
COUNTER = "COUNTER"
HOLD = "HOLD"
ASK_ACCEPT = "ASK_ACCEPT"  # needs sign-off to accept the other side's number
ASK_OFFER = "ASK_OFFER"  # needs sign-off to move to our next position


@dataclass(frozen=True)
class ClausePolicy:
    key: str
    prefers: str  # "low", "high" or "order"
    ladder: tuple[float | str, ...]
    auto_through: float | str
    signoff_through: float | str
    rationale: str = ""

    def rank(self, value: float | str) -> float:
        """Lower is better for us. Unknown choices rank as unacceptable."""
        if self.prefers == "low":
            return float(value)
        if self.prefers == "high":
            return -float(value)
        return float(self.ladder.index(value)) if value in self.ladder else float("inf")

    def acceptable_automatically(self, value: float | str) -> bool:
        return self.rank(value) <= self.rank(self.auto_through)

    def within_signoff(self, value: float | str) -> bool:
        return self.rank(value) <= self.rank(self.signoff_through)


@dataclass(frozen=True)
class Decision:
    action: str
    value: float | str


@dataclass
class ClauseState:
    position: int = -1  # index into the ladder of our latest offer


@dataclass
class Playbook:
    company: str
    authority: str  # the Mattermost username allowed to sign off
    canary: str  # planted so that leak checks can search for it
    policies: dict[str, ClausePolicy]
    state: dict[str, ClauseState] = field(default_factory=dict)

    @classmethod
    def load(cls, path: Path) -> "Playbook":
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        policies = {}
        for key, raw in data["clauses"].items():
            if key not in CLAUSES:
                raise ValueError(f"{path}: unknown clause {key}")
            ladder = tuple(parse_value(key, str(v)) for v in raw["ladder"])
            policies[key] = ClausePolicy(
                key=key,
                prefers=raw["prefers"],
                ladder=ladder,
                auto_through=parse_value(key, str(raw["auto_through"])),
                signoff_through=parse_value(key, str(raw["signoff_through"])),
                rationale=raw.get("rationale", ""),
            )
        return cls(data["company"], data["authority"], data["canary"], policies)

    def reset(self) -> None:
        self.state = {}

    def _state(self, key: str) -> ClauseState:
        return self.state.setdefault(key, ClauseState())

    def current_offer(self, key: str) -> float | str | None:
        position = self._state(key).position
        return self.policies[key].ladder[position] if position >= 0 else None

    def opening(self, key: str) -> Decision:
        state = self._state(key)
        state.position = max(state.position, 0)
        return Decision(COUNTER, self.policies[key].ladder[state.position])

    def review(self, key: str, value: float | str) -> Decision:
        """Decide what to do about the other side's proposal."""
        policy = self.policies[key]
        state = self._state(key)
        current = self.current_offer(key)
        if current is not None and policy.rank(value) <= policy.rank(current):
            return Decision(ACCEPT, value)
        if policy.acceptable_automatically(value):
            return Decision(ACCEPT, value)

        following = policy.ladder[state.position + 1] if state.position + 1 < len(policy.ladder) else None
        if following is not None and policy.acceptable_automatically(following):
            state.position += 1
            return Decision(COUNTER, following)

        # Delegated room is used up, so a person has to decide from here.
        if policy.within_signoff(value):
            return Decision(ASK_ACCEPT, value)
        if following is not None and policy.within_signoff(following):
            return Decision(ASK_OFFER, following)
        return Decision(HOLD, current if current is not None else policy.ladder[0])

    def record_offer(self, key: str, value: float | str) -> None:
        """Remember a position the General Counsel authorised, so we never drift back from it."""
        policy = self.policies[key]
        state = self._state(key)
        if value in policy.ladder:
            state.position = max(state.position, policy.ladder.index(value))
