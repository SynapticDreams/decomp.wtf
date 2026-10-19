"""Physical ROM reference checks for SMS assembly, separate from assembler section placement."""
from __future__ import annotations

import re

from . import z80
from .sms_mapping import BANK, Address, BusState, Mapper, entry_state


def reference(routine, target: int, offset: int = 0) -> Address:
    """Resolve using the routine's explicit entry context, else only conditional source-window evidence."""
    try:
        model = Mapper(routine.mapper, routine.rom_size or routine.banks * BANK)
    except ValueError as exc:
        return Address(target, "unknown", reason=str(exc))
    state = routine.mapping if routine.mapping is not None else entry_state(routine.flat, routine.cpu, model.size)
    # Do not reuse an entry bank after a store changes its selection. Value/path summaries are not
    # established here, so known mapper stores use unknown values rather than guessing an A/HL value.
    for cpu, text, _length in z80.disassemble(routine.code[:offset], routine.cpu):
        flat = routine.flat + cpu - routine.cpu
        if any(lo <= flat < lo + count for lo, count, _kind in routine.data):
            continue
        if match := re.match(r"^ld \(\$([0-9a-f]{4})\), (.+)$", text):
            count = 2 if match.group(2) in ("hl", "de", "bc", "sp", "ix", "iy") else 1
            for byte in range(count):
                state = model.write(state, (int(match.group(1), 16) + byte) & 0xFFFF, None)
        elif re.match(r"^(?:ld \((?:bc|de|hl|ix|iy)|(?:inc|dec|rlc|rrc|rl|rr|sla|sra|sll|srl) \((?:hl|ix|iy)|"
                      r"(?:res|set) \d, \((?:hl|ix|iy))", text) or \
                text.startswith(("out ($3e)", "out (c)", "ldi", "ldd", "ex (sp)")):
            state = BusState()  # an unqualified indirect/bus write can affect the source
    return model.resolve(target, state)


def bank_checks(routine, layout, operands) -> list[str]:
    """A unique named CPU address does not establish its physical bank or even a ROM source."""
    out = []
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
        address = reference(routine, value, offset)
        if address.rom_offset is None:
            out.append(f"3. line {item.line}: the cartridge ROM target at ${value:04X} isn't known yet "
                       f"({address.reason or address.space}); keep the reference pending until its mapping is established")
            continue
        for name in used:
            if flats[name] != address.offset:
                out.append(f"3. line {item.line}: {name} is in bank {flats[name] // BANK}, but at ${value:04X} "
                           f"this routine reaches bank {address.bank}")
    return out
