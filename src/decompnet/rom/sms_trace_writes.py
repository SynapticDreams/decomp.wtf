"""Apply explicit write effects to mapper and sparse path-local memory facts."""
from __future__ import annotations

from dataclasses import replace

from .sms_effects import Write
from .sms_mapping import Mapper, wram_address
from .sms_state import State


def limits(writes: tuple[Write, ...], model: Mapper) -> set[str]:
    reasons = set()
    if model.kind == "codemasters":
        for write in writes:
            if write.cpu is not None and write.cpu < 0xC000 and not model.is_mapper_register(write.cpu):
                reasons.add("Codemasters selector mirror decoding is not qualified")
            elif write.cpu == 0x4000 and (type(write.value) is not int or write.value & 0x80):
                reasons.add("Codemasters upper-slot RAM wiring is undeclared")
    return reasons


def apply(state: State, writes: tuple[Write, ...], source_change: bool, model: Mapper) -> None:
    for write in writes:
        if write.cpu is None:
            state.mapping = model.unknown_write(state.mapping)
            state.mem.clear()
            state.stack.clear()  # an unqualified write can overwrite a saved value
            continue
        if write.size > 1:  # (memory_writes gives a size only to copies wholly within $C000-$DFFF)
            for at in range(write.cpu, write.cpu + write.size):
                state.mem.pop(at, None)
            continue
        value = write.value
        state.mapping = model.write(state.mapping, write.cpu, value if type(value) is int else None)
        if (alias := wram_address(write.cpu)) is not None:
            if value is not None and model.resolve(write.cpu, state.mapping).space == "wram":
                state.mem[alias] = value
            else:
                state.mem.pop(alias, None)
    if source_change:
        state.mapping = replace(state.mapping, cartridge=None, bios=None, wram=None, other_source=None)
        state.mem.clear()
        state.stack.clear()
