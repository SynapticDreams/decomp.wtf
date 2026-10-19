"""Bounded visitation of path-local facts, independent of SMS instruction semantics.

Absolute instruction counts cannot be convergence keys: an unchanged loop would never converge.
Fresh table/bound marks instead retain their age until expiry, and then become indistinguishable.
Limits describe this traversal only; they do not establish complete control flow or CPU emulation.
"""
from __future__ import annotations

from dataclasses import dataclass

from .sms_state import FRESH, State


@dataclass(frozen=True)
class Limits:
    steps: int = 16384
    per_pc: int = 32
    stack: int = 32
    memory: int = 256

    def __post_init__(self):
        for value in (self.steps, self.per_pc, self.stack, self.memory):
            if type(value) is not int or not 1 <= value <= 1_000_000:
                raise ValueError("trace limits must be positive integers no greater than 1000000")


def signature(state: State) -> tuple:
    def mark(value):
        if value is None or state.n - value[0] > FRESH:
            return None
        return (state.n - value[0], *value[1:])

    return (state.mapping, state.a, state.hl, state.de, state.bc,
            frozenset(state.mem.items()), tuple(state.stack), state.pushed,
            state.sp, state.stack_top, min(state.n, 3),
            *(mark(getattr(state, name)) for name in ("cmp", "low", "bound", "index", "base")))


class Paths:
    """A per-function work budget; duplicates converge without consuming more steps."""
    def __init__(self, limits: Limits):
        self.limits = limits
        self.seen: dict[tuple[int, int], set[tuple]] = {}
        self.steps = 0
        self.exhausted: set[str] = set()

    def admit(self, flat: int, cpu: int, state: State) -> bool:
        if len(state.stack) > self.limits.stack:
            self.exhausted.add("stack budget exhausted")
            return False
        if len(state.mem) > self.limits.memory:
            self.exhausted.add("memory budget exhausted")
            return False
        facts = signature(state)
        seen = self.seen.setdefault((flat, cpu), set())
        if facts in seen:
            return False
        if self.steps >= self.limits.steps:
            self.exhausted.add("instruction budget exhausted")
            return False
        if len(seen) >= self.limits.per_pc:
            self.exhausted.add("context budget exhausted")
            return False
        seen.add(facts)
        self.steps += 1
        return True
