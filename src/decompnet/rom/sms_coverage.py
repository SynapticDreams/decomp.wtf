"""Translate cartridge-ROM execution coordinates without guessing other mapped windows.

The text format declares a physical cartridge bank and CPU address per observed instruction.
It cannot represent BIOS/RAM execution or provide full bus state. Explicit gaps break entry evidence;
the absence of gap markers cannot establish that a capture is complete.
Durable session identity and richer trace formats belong to the session evidence layer.
"""
from __future__ import annotations

from . import z80
from .coverage import Coverage, CoverageError, _TRACE
from .sms_mapping import Mapper
from .sms_mapping import rom_coordinate as trace_address
from .sms_profile import read as read_profile


def from_config(text: str, rom: bytes, cfg: dict) -> Coverage:
    try:
        mapper = read_profile(cfg)["mapper"]
    except (ValueError, TypeError) as exc:
        raise CoverageError(str(exc)) from exc
    return read_trace(text, rom, mapper=mapper)


def read_trace(text: str, rom: bytes, *, mapper: str) -> Coverage:
    """Read ROM-only observations; adjacent call/target records provide observed entry candidates.

    Unknown profiles must be declared before interpretation. Rejected lines and gaps never bridge a call to
    an unrelated occurrence of its target. Byte fetches stop when their window/source is not established.
    """
    try:
        model = Mapper(mapper, len(rom))
    except ValueError as exc:
        raise CoverageError("SMS/GG ROM traces need a declared supported model in project Settings") from exc
    cov = Coverage(bytearray(len(rom)), bytearray(len(rom)), kind="trace")
    previous = None
    seen = False
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith(";"):
            continue
        match = _TRACE.match(line)
        if not match:
            previous = None
            continue
        bank, cpu = (int(value, 16) for value in match.groups())
        result = trace_address(model, bank, cpu)
        if (flat := result.rom_offset) is None:
            previous = None
            continue
        seen = True
        cov.cpus.setdefault(flat, set()).add(cpu)
        cov.code[flat] = 1  # even an incompletely fetched instruction has an observed first byte
        if previous is not None and previous[0] == cpu and (previous[1] is None or previous[1] == flat):
            cov.entries.add(flat)
        state = model.entry(flat, cpu)
        chunk = bytearray()
        for offset in range(4):
            address = model.resolve(cpu + offset, state)
            if address.rom_offset is None:
                break
            chunk.append(rom[address.offset])
        instruction, length = z80.decode(bytes(chunk), cpu)
        previous = None
        if instruction.startswith("db ") or length > len(chunk):
            continue
        for offset in range(length):
            cov.code[model.resolve(cpu + offset, state).offset] = 1
        kind, target = z80.flow(instruction)
        if kind == "call":
            previous = (target, model.resolve(target, state).rom_offset)
    if not seen:
        raise CoverageError("no valid cartridge-ROM `bank:address` instructions in this execution trace")
    return cov
