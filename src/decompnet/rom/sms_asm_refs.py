"""Physical ROM reference checks for SMS assembly, separate from assembler section placement."""
from __future__ import annotations

import re

from . import sms_effects, z80
from .sms_mapping import BANK, Address, BusState, Mapper, entry_state


def _prefix(routine, offset):
    cursor = 0
    while cursor < min(offset, len(routine.code)):
        end = next((lo + count - routine.flat for lo, count, _kind in routine.data
                    if lo <= routine.flat + cursor < lo + count), None)
        if end is not None:
            cursor = end
            continue
        text, length = z80.decode(routine.code[cursor:cursor + 4], routine.cpu + cursor)
        yield text
        cursor += max(1, length)


def reference(routine, target: int, offset: int = 0, *, prefix=None) -> Address:
    """Resolve using the routine's explicit entry context, else only conditional source-window evidence."""
    try:
        model = Mapper(routine.mapper, routine.rom_size or routine.banks * BANK)
    except ValueError as exc:
        return Address(target, "unknown", reason=str(exc))
    state = routine.mapping if routine.mapping is not None else entry_state(routine.flat, routine.cpu, model.size)
    # Do not reuse an entry bank after a store changes its selection. Value/path summaries are not
    # established here, so known mapper stores use unknown values rather than guessing an A/HL value.
    for text in prefix if prefix is not None else _prefix(routine, offset):
        for write in sms_effects.memory_writes(text):
            state = model.unknown_write(state) if write.cpu is None else model.write(state, write.cpu, None)
        if sms_effects.port_may_change_source(text):
            state = BusState()  # hardware/mode-specific bus enables are not qualified here
    return model.resolve(target, state)


def bank_checks(routine, layout, operands) -> list[str]:
    """A unique named CPU address does not establish its physical bank or even a ROM source."""
    out = []
    if (source := reference(routine, routine.cpu)).rom_offset != routine.flat:
        out.append("3. the routine's CPU/physical source coordinate is not established cartridge ROM "
                   f"({source.reason or source.space})")
    flats = {name: flat for flat, name in routine.functions.items()}
    for item, offset, text, length in layout:
        if item.kind != "insn" or (operand := operands(text, length)) is None:
            continue
        role, value, _positions = operand
        if not 0 <= value < 0xC000 or role in ("write", "port"):
            continue
        used = [name for name in re.findall(r"[A-Za-z_]\w*", item.text) if name in flats]
        if not used:
            continue
        prefix = [text for it, off, text, _ln in layout if it.kind == "insn" and off < offset]
        address = reference(routine, value, offset, prefix=prefix)
        if address.rom_offset is None:
            out.append(f"3. line {item.line}: the cartridge ROM target at ${value:04X} isn't known yet "
                       f"({address.reason or address.space}); keep the reference pending until its mapping is established")
            continue
        for name in used:
            if flats[name] != address.offset:
                out.append(f"3. line {item.line}: {name} is in bank {flats[name] // BANK}, but at ${value:04X} "
                           f"this routine reaches bank {address.bank}")
    return out
