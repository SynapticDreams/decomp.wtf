"""Qualified Codemasters selector effects; undeclared mirror/RAM wiring stays unknown.

SMS Power documents whole-window mirrors; Gearsystem decodes only canonical addresses and
gates RAM by board capability. We qualify their common selector addresses, not either disputed
mirror recipe. Bit 7 here describes effective upper-slot RAM selection, not a raw latch.
"""
from dataclasses import replace

SELECTORS = {0x0000: 0, 0x4000: 1, 0x8000: 2}
RAM = 0x80


def write(state, cpu: int, value: int | None, mask: int):
    if cpu >= 0xC000:
        return state
    slot = cpu // 0x4000
    banks, registers = list(state.banks), list(state.registers)
    qualified = cpu in SELECTORS and state.cartridge is True
    registers[slot] = value if qualified else None
    banks[slot] = value & mask if qualified and value is not None else None
    update = {"banks": tuple(banks), "registers": tuple(registers)}
    if slot == 1:
        # A clear flag proves ROM. A set/unknown flag cannot establish RAM presence without
        # a board declaration; it must not expose the original ROM bytes as if RAM were absent.
        rom = qualified and value is not None and not value & RAM
        update.update(control=0 if rom else None, control_known=RAM if rom else 0)
    return replace(state, **update)
