"""Whole-discovery resource accounting, shared across tracer rounds and discovery passes."""
from __future__ import annotations

from dataclasses import asdict, dataclass

from .sms_mapping import Mapper, join

CONVERGENCE_ROUNDS = 8
GAP_PASSES = 8


@dataclass(frozen=True)
class AnalysisLimits:
    entries: int = 4000
    instructions: int = 1_000_000
    call_instructions: int = 262144
    rounds: int = 64

    def __post_init__(self):
        for value in asdict(self).values():
            if type(value) is not int or not 1 <= value <= 16_000_000:
                raise ValueError("analysis limits must be positive integers no greater than 16000000")


class Budget:
    def __init__(self, limits: AnalysisLimits | None = None):
        self.limits = limits or AnalysisLimits()
        self.entries: set[tuple[int, int]] = set()
        self.instructions = self.call_instructions = self.rounds = 0
        self.exhausted: set[str] = set()
        self.stopped = False

    def note(self, reason: str, *, stop: bool = False):
        self.exhausted.add(reason)
        self.stopped |= stop

    def _take(self, name, reason):
        if self.stopped:
            return False
        if getattr(self, name) >= getattr(self.limits, name):
            self.note(reason, stop=True)
            return False
        setattr(self, name, getattr(self, name) + 1)
        return True

    def round(self):
        return self._take("rounds", "analysis round budget exhausted")

    def step(self, *, call=False):
        if self.stopped:
            return False
        if self.instructions >= self.limits.instructions:
            self.note("analysis instruction budget exhausted", stop=True)
            return False
        if call and self.call_instructions >= self.limits.call_instructions:
            self.note("analysis call instruction budget exhausted", stop=True)
            return False
        self.instructions += 1
        self.call_instructions += int(call)
        return True

    def enter(self, flat, cpu):
        if self.stopped:
            return False
        if (flat, cpu) not in self.entries:
            if len(self.entries) >= self.limits.entries:
                self.note("analysis entry budget exhausted", stop=True)
                return False
            self.entries.add((flat, cpu))
        return True

    def seeds(self, entries):
        if len(entries) <= self.limits.entries:
            return entries
        self.note("analysis entry seed limit exhausted")
        return dict(sorted(entries.items())[:self.limits.entries])

    def qualify(self, found, model: Mapper):
        if not self.exhausted:
            return
        # Missing callers/rounds cannot establish a complete incoming mapper context. Retain the
        # coordinates of conditional entries, without exporting singleton cross-window facts.
        for flat, (cpu, _why) in found.starts.items():
            found.entered[flat] = {join((*found.entered.get(flat, ()), model.entry(flat, cpu)))}
            found.exhausted.setdefault(flat, set()).update(self.exhausted)
        found.switchers.clear()
        found.with_hl.clear()
        found.indexed.clear()

    def report(self):
        return {"limits": asdict(self.limits), "used": {"entries": len(self.entries),
                "instructions": self.instructions, "call_instructions": self.call_instructions, "rounds": self.rounds},
                "exhausted": sorted(self.exhausted)}


class Session:
    """Keep accounting and diagnostic evidence when discovery retraces with additional seeds."""
    def __init__(self, factory, budget: Budget):
        self.factory, self.budget = factory, budget
        self.last = None
        self.exhausted: dict[int, set[str]] = {}
        self.unresolved: dict[int, set[str]] = {}

    def _collect(self, found):
        for at, reasons in found.exhausted.items():
            self.exhausted.setdefault(at, set()).update(reasons)
        for at, reasons in found.unresolved.items():
            self.unresolved.setdefault(at, set()).update(reasons)

    def follow(self, entries):
        if self.budget.stopped and self.last is not None:
            return self.last
        tracer = self.factory(self.budget)
        found = tracer.follow(entries)
        if self.budget.stopped and not found.starts and self.last is not None:
            return self.last
        self._collect(found)
        self.last = tracer, found
        return self.last

    def report(self, found, model, output_limit):
        if len(found.starts) > output_limit:
            self.budget.note("candidate output limit exhausted")
        self.budget.qualify(found, model)
        self._collect(found)
        return {"analysis_limits": {**self.budget.report(), "candidate_output_limit": output_limit,
                                    "convergence_round_limit": CONVERGENCE_ROUNDS, "gap_pass_limit": GAP_PASSES},
                "analysis_exhausted": [{"rom_offset": at, "reasons": sorted(reasons)}
                                       for at, reasons in sorted(self.exhausted.items())],
                "analysis_unresolved": [{"rom_offset": at, "reasons": sorted(reasons)}
                                        for at, reasons in sorted(self.unresolved.items())]}
