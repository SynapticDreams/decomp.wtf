"""Explicit memory/port writes in normalized Z80 text, without traversal or CPU emulation.

Unknown block lengths stay unbounded. Implicit PUSH/CALL stack traffic is outside this adapter;
the tracer still uses a virtual stack and does not qualify arbitrary physical stack placement.
"""
from __future__ import annotations

from dataclasses import dataclass
import re


@dataclass(frozen=True)
class Write:
    cpu: int | None
    value: object = None
    size: int = 1  # (a block copy into work RAM: `size` bytes from `cpu`, values unknown)


def _value(name, values):
    if name.startswith("$"):
        return int(name[1:], 16)
    if name in values:
        return values[name]
    pair = {"b": "bc", "c": "bc", "d": "de", "e": "de", "h": "hl", "l": "hl"}.get(name)
    value = values.get(pair)
    return (value >> (8 if name in ("b", "d", "h") else 0)) & 255 if type(value) is int else None


def memory_writes(text: str, values: dict | None = None) -> tuple[Write, ...]:
    values = values or {}

    def address(operand):
        return int(operand[1:], 16) if operand.startswith("$") else values.get(operand)

    if match := re.fullmatch(r"ld \(([^)]+)\), (.+)", text):
        at, source = address(match[1]), match[2]
        value = _value(source, values)
        if source in ("hl", "bc", "de", "sp", "ix", "iy"):
            return tuple(Write((at + byte) & 65535 if type(at) is int else None,
                               (value >> (8 * byte)) & 255 if type(value) is int else None) for byte in (0, 1))
        return (Write(at, value),)
    if match := re.match(r"^(?:(?:inc|dec|rlc|rrc|rl|rr|sla|sra|sll|srl) |(?:res|set) \d, )\(([^)]+)\)", text):
        return (Write(address(match[1])),)
    if text in ("rrd", "rld"):
        return (Write(values.get("hl")),)
    if text in ("ldi", "ldd", "ini", "ind"):
        return (Write(values.get("de" if text in ("ldi", "ldd") else "hl")),)
    if text in ("ldir", "lddr"):
        de, count = values.get("de"), values.get("bc")
        low = (de if text == "ldir" else de - count + 1) if type(de) is int and type(count) is int and count else None
        if low is not None and 0xC000 <= low and low + count <= 0xE000:
            return (Write(low, None, count),)  # wholly in work RAM: no mapper register or ROM byte in reach
    if text in ("ldir", "lddr", "inir", "indr") or text.startswith("ex (sp), "):
        # Multiple unqualified writes may first enable ROM writes and then alter cartridge contents.
        return (Write(None), Write(None))
    return ()


def port_may_change_source(text: str, bc: int | None = None, *, game_gear: bool = False) -> bool:
    """Stop on memory-control writes, possible mirrors and unknown output ports.

    Hardware/mode-specific enables and mirror exceptions are unqualified, so even a known value
    does not establish a new bus source. Known VDP/PSG/I/O-control outputs preserve mapper facts.
    `game_gear`: a Game Gear cartridge in its own mode, where ports $00-$06 are the console's registers
    (Start/region, link, PSG stereo) and never reach memory control. Other even ports stay possible mirrors.
    """
    if match := re.match(r"^out \((\$[0-9a-f]{2}|c)\),", text):
        port = int(match[1][1:], 16) if match[1].startswith("$") else bc
    elif text in ("outi", "outd", "otir", "otdr"):
        port = bc
    else:
        return False
    if port is not None and game_gear and port & 0xFF <= 0x06:
        return False
    return port is None or (port & 0xC1) == 0


def copied_register(text: str) -> str | None:
    """Indexed CB writes can also replace an ordinary register with an unknown result."""
    match = re.fullmatch(r"(?:rlc|rrc|rl|rr|sla|sra|sll|srl|res \d,|set \d,) \(i[xy][^)]+\), ([abcdehl])", text)
    return match[1] if match else None


def interrupt_limit(text: str) -> str | None:
    if text in ("ei", "halt"):
        return "asynchronous interrupt-dependent continuation is unqualified"
    if text in ("reti", "retn"):
        return "interrupt return and bank/stack preservation are unqualified"
    return None
