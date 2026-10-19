"""SMS research locations: explicit cartridge coordinates or references under an established context."""
from __future__ import annotations

import re

from .sms_mapping import BANK, BusState, Mapper, entry_state, rom_coordinate


def coordinate(model: Mapper, flat: int, cpu: int) -> tuple[int, int]:
    address = rom_coordinate(model, flat // BANK, cpu)
    if address.rom_offset != flat:
        raise ValueError("the function's CPU/physical coordinate isn't in the ROM under the selected mapping")
    return flat, cpu


def resolve(model: Mapper, text: str, context: tuple[int, int] | None = None) -> tuple[int, int]:
    explicit = re.fullmatch(r"(?:0x|\$)?([0-9A-Fa-f]{1,4}):(?:0x|\$)?([0-9A-Fa-f]{1,4})", text)
    if explicit:
        bank, cpu = (int(value, 16) for value in explicit.groups())
        address = rom_coordinate(model, bank, cpu)
    elif re.fullmatch(r"(?:0x|\$)?[0-9A-Fa-f]{1,4}", text):
        cpu = int(text.removeprefix("0x").removeprefix("$"), 16)
        state = BusState.cartridge_only(control=None)
        if context is not None:
            flat, here = coordinate(model, *context)
            state = entry_state(flat, here, model.size)
        address = model.resolve(cpu, state)
    else:
        raise ValueError(f"`{text}` is not a function, NN:AAAA (a bank and an address) or an address")
    if address.rom_offset is None:
        raise ValueError(f"{text} isn't in the ROM under the selected mapping/context "
                         f"({address.reason or address.space}); use explicit NN:AAAA coordinates")
    return address.offset, cpu
