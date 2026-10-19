"""Apply explicit write effects to mapper and sparse path-local memory facts."""
from __future__ import annotations

from dataclasses import replace

from .sms_effects import Write
from .sms_mapping import Mapper, wram_address
from .sms_state import State


def apply(state: State, writes: tuple[Write, ...], source_change: bool, model: Mapper) -> None:
    for write in writes:
        if write.cpu is None:
            state.mapping = model.unknown_write(state.mapping)
            state.mem.clear()
            state.stack.clear()  # an unqualified write can overwrite a saved value
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
