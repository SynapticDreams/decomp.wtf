"""Candidate coordinates from symbols, cold call scans and declared near-pointer tables.

These are research seeds, not execution evidence. Section placement never establishes a live bank.
Symbol/table CPU coordinates are explicit declarations; an unqualified call scan has no pageable-bank facts.
"""
from __future__ import annotations

from .sms_mapping import BANK, BusState, Mapper, entry_state, rom_coordinate

CALLS = (0xCD, 0xC4, 0xCC, 0xD4, 0xDC, 0xE4, 0xEC, 0xF4, 0xFC)


def call_targets(data: bytes, bank: int, model: Mapper, skip=None):
    """Yield resolvable (physical target, CPU target) pairs without borrowing presentation defaults."""
    state = BusState.cartridge_only(control=None)
    low, high = bank * BANK, min((bank + 1) * BANK, len(data))
    for offset in range(low, high - 2):
        if data[offset] not in CALLS or (skip and skip(offset)):
            continue
        cpu = int.from_bytes(data[offset + 1:offset + 3], "little")
        address = model.resolve(cpu, state)
        if address.rom_offset is not None:
            yield address.offset, cpu


def symbol_targets(labels, model: Mapper):
    for bank, cpu in labels:
        address = rom_coordinate(model, bank, cpu)
        if address.rom_offset is not None:
            yield address.offset, cpu


def table_targets(data: bytes, tables, cpus: dict, model: Mapper):
    """Near pointers use an explicitly declared table window; undeclared windows stay unknown."""
    for flat, count in tables:
        if not 0 <= flat < len(data):
            continue
        cpu = cpus.get(flat)
        state = BusState.cartridge_only(control=None)
        if cpu is not None:
            address = rom_coordinate(model, flat // BANK, cpu)
            if address.rom_offset != flat:
                continue
            state = entry_state(flat, cpu, model.size)
        for index in range(min(count, (len(data) - flat) // 2)):
            offset = flat + 2 * index
            target = int.from_bytes(data[offset:offset + 2], "little")
            address = model.resolve(target, state)
            if address.rom_offset is not None:
                yield address.offset, target
