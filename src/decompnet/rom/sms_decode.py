"""Bounded Z80 cartridge decoding and provisional code-entry checks."""
from __future__ import annotations

import re

from . import z80

BANK = 0x4000


def decode(data: bytes, flat: int, cpu: int) -> tuple[str, int]:
    end = min(len(data), (flat // BANK + 1) * BANK)
    return z80.decode(data[flat:min(end, flat + 4)], cpu)


def can_start(data: bytes, flat: int, cpu: int) -> bool:
    """Where a call or jump can land: an instruction, and not the $FF filler of an empty bank (`rst $38` again and
    again)."""
    if not 0 <= flat < len(data) or data[flat:flat + 2] == b"\xff\xff":
        return False
    return not decode(data, flat, cpu)[0].startswith("db ")


_ODD_START = re.compile(r"^(?:nop|ld \(bc\), a|ld \(de\), a|ex af|halt|rst |daa|ccf|scf|di$|ei$|ld ([a-e]), \1$)")


def plausible(data: bytes, flat: int, cpu: int, limit: int = 64) -> bool:
    """For an address that's only a guess (a word in a table): code that reads like a function's start: no filler or
    undefined opcodes, not what tables of numbers decode to first, and a return or jump within `limit` instructions
    in the bank."""
    if not can_start(data, flat, cpu) or data[flat:flat + 2] == b"\x00\x00":
        return False
    for k in range(limit):
        text, ln = decode(data, flat, cpu)
        if text.startswith("db ") or text == "rst $38" or (k == 0 and _ODD_START.match(text)):
            return False
        if z80.flow(text)[0] in ("ret", "jump"):
            return True
        flat, cpu = flat + max(1, ln), cpu + max(1, ln)
        if flat % BANK == 0:
            return False
    return False

