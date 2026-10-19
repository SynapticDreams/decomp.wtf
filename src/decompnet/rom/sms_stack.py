"""Bounded guards for known physical stacks under the ordinary virtual-stack contract.

Only unambiguous work RAM away from mapper registers qualifies. Explicit writes into active
stack storage, including its mirror, stop interpretation. Unknown SP retains the documented
virtual-stack assumption; this is not physical stack or interrupt emulation.
"""
from __future__ import annotations

from dataclasses import dataclass

from .sms_mapping import Mapper, wram_address
from .sms_state import State

MAX_BYTES = 512


@dataclass(frozen=True)
class StackWord:
    kind: str
    value: object


def take(state: State):
    saved = state.stack.pop() if state.stack else None
    return (saved.value, saved.kind) if isinstance(saved, StackWord) else (saved, None)


def address(state: State):
    if not state.stack or not isinstance(saved := state.stack[-1], StackWord) or saved.kind not in ("hl", "de", "bc", "ix", "iy"):
        return None
    value = saved.value
    return value if type(value) is int and 0 <= value <= 65535 else None


def _count(state: State):
    if state.sp is None or state.stack_top is None:
        return 0
    count = (state.stack_top - state.sp) & 65535
    if count > MAX_BYTES:
        return None
    return count


def _overlaps(state, cpu, count):
    alias = wram_address(cpu)
    base = wram_address(state.sp) if state.sp is not None else None
    return bool(count and alias is not None and base is not None and ((alias - base) & 0x1FFF) < count)


def _addresses(state, model, addresses):
    if any(model.resolve(at, state.mapping).space != "wram" or model.is_mapper_register(at) for at in addresses):
        return "physical stack may access a mapper or unqualified memory source"
    return None


def push(state: State, model: Mapper, *, apply=True):
    if state.sp is None:
        return None
    addresses = ((state.sp - 1) & 65535, (state.sp - 2) & 65535)
    if reason := _addresses(state, model, addresses):
        return reason
    count = _count(state)
    if count is None:
        return "physical stack tracking budget exhausted"
    if count + 2 > MAX_BYTES:
        return "physical stack tracking budget exhausted"
    aliases = {wram_address(at) for at in addresses}
    if any(_overlaps(state, at, count) for at in addresses):
        return "physical stack mirror overlaps an active saved value"
    if apply:
        if state.stack_top is None:
            state.stack_top = state.sp
        state.sp = addresses[1]
        for alias in aliases:
            state.mem.pop(alias, None)  # pushed physical bytes are not supplied as RAM-readback facts
    return None


def pop(state: State, model: Mapper, *, apply=True):
    if state.sp is None:
        return None
    if reason := _addresses(state, model, (state.sp, (state.sp + 1) & 65535)):
        return reason
    count = _count(state)
    if count is None:
        return "physical stack tracking budget exhausted"
    if state.stack_top is None or count < 2:
        return "physical stack pop exceeds its tracked active range"
    if apply:
        state.sp = (state.sp + 2) & 65535
    return None


def write_alias(state: State, writes):
    if not writes:
        return None
    count = _count(state)
    if count is None:
        return "physical stack tracking budget exhausted"
    if any(write.cpu is not None and _overlaps(state, write.cpu, count) for write in writes):
        return "memory write aliases an active physical stack value"
    return None


def instruction(state: State, text: str, kind: str, model: Mapper):
    if kind == "call":
        return push(state, model, apply=False)  # the evaluator accounts for its actual return-word push
    if text.startswith("push "):
        return push(state, model)
    if text.startswith("pop ") or text.split()[0] in ("ret", "reti", "retn"):
        return pop(state, model, apply=kind != "cret")
    return None
