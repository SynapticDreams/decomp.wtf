"""SDCC library recognition for the Z80 lanes: signatures made from library objects, matched only where unique.

SDCC's libraries are `ar` archives of ASxxxx relocatable objects (`XL4`: hex, little-endian, four-byte addresses).
Each `T` record places code bytes at an area offset and the `R` record after it says which of those bytes the linker
rewrites; those become wildcards, so a function matches wherever it was linked. `R_BYT2` byte relocations carry two
bytes in the record for one byte of output. Symbols listed after an area are defined in it.

The signatures come from the libraries a person has: the pinned GBDK-2020's own, and any further `.lib`/`.rel` files
they provide (devkitSMS's SMSlib.lib, for example). Nothing of them is bundled. A match names a library function
and the library it came from; it does not establish the compiler that built the game's own code.
"""
from __future__ import annotations

from dataclasses import dataclass
import re
import time

from . import psyq

MAX_BYTES = 64 << 20  # per scan, libraries included
MIN_LENGTH, MIN_CONCRETE, MIN_ANCHOR = 16, 12, 4
CODE_AREAS = re.compile(r"^_(?:CODE(?:_\w+)?|HOME|BASE|GSINIT|GSFINAL)$")
_KNOWN_MODES = 0x01 | 0x02 | 0x04 | 0x08 | 0x80  # byte, symbol, PC-relative, two-byte record, high byte


@dataclass(frozen=True)
class Function:
    library: str
    module: str
    area: str
    pattern: tuple[int | None, ...]
    labels: tuple[tuple[str, int], ...]  # (symbol, offset in the pattern)


def ar_members(data: bytes) -> list[tuple[str, bytes]]:
    """(name, contents) of a System V / GNU `ar` archive, as sdar writes them."""
    if not data.startswith(b"!<arch>\n"):
        raise ValueError("not an ar archive")
    at, names, out = 8, b"", []
    while at + 60 <= len(data):
        header = data[at:at + 60]
        if header[58:60] != b"`\n":
            raise ValueError("malformed ar member header")
        name, size = header[:16].decode("latin-1").strip(), int(header[48:58].decode("ascii").strip() or 0)
        body = data[at + 60:at + 60 + size]
        at += 60 + size + (size & 1)
        if name == "//":
            names = body
        elif name in ("/", "/SYM64/", "__.SYMDEF"):
            continue
        else:
            if name.startswith("/") and name[1:].isdigit():
                start = int(name[1:])
                name = names[start:names.index(b"\n", start)].decode("latin-1")
            out.append((name.rstrip("/"), body))
    return out


def parse_rel(text: str, library: str = "", module: str = "") -> list[Function]:
    """The code areas of one ASxxxx `XL4` object, as wildcard patterns with their defined symbols."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "XL4":
        raise ValueError("expected an SDCC/ASxxxx XL4 object")
    areas: list[str] = []
    sizes: dict[str, int] = {}
    symbols: dict[str, list[tuple[str, int]]] = {}
    output: dict[str, dict[int, int | None]] = {}
    pending: tuple[int, list[int]] | None = None
    for raw in lines[1:]:
        parts = raw.split()
        if not parts:
            continue
        if parts[0] == "M" and len(parts) > 1:
            module = module or parts[1]
        elif parts[0] == "A" and len(parts) >= 4:
            areas.append(parts[1])
            sizes[parts[1]] = int(parts[3], 16)
        elif parts[0] == "S" and len(parts) >= 3 and parts[2].startswith("Def") and areas:
            symbols.setdefault(areas[-1], []).append((parts[1], int(parts[2][3:], 16)))
        elif parts[0] == "T":
            values = [int(x, 16) for x in parts[1:]]
            if len(values) < 4:
                raise ValueError("short T record")
            pending = (values[0] | values[1] << 8 | values[2] << 16 | values[3] << 24, values)
        elif parts[0] == "R" and pending is not None:
            values = [int(x, 16) for x in parts[1:]]
            if len(values) < 4 or (len(values) - 4) % 4:
                raise ValueError("malformed R record")
            area = values[2] | values[3] << 8
            if area >= len(areas):
                raise ValueError("relocation names an undefined area")
            relocations = {}
            for k in range(4, len(values), 4):
                mode, offset = values[k], values[k + 1]
                if mode & ~_KNOWN_MODES:
                    raise ValueError(f"unsupported relocation mode {mode:#04x}")
                relocations[offset] = mode
            address, record = pending
            place, i = output.setdefault(areas[area], {}), 4
            while i < len(record):
                mode = relocations.get(i)
                if mode is None:
                    place[address] = record[i]
                    address, i = address + 1, i + 1
                    continue
                width = 1 if mode & 0x01 else 2
                for _ in range(width):
                    place[address] = None
                    address += 1
                i += 2 if mode & 0x01 and mode & 0x08 else width
            pending = None
    out = []
    for area, place in output.items():
        if not CODE_AREAS.match(area) or not place:
            continue
        size = sizes.get(area, 0)
        if size != max(place) + 1 or len(place) != size:
            raise ValueError(f"{module}: area {area} records don't cover its {size} bytes")
        labels = tuple(sorted((name, at) for name, at in symbols.get(area, [])
                              if 0 <= at < size and psyq.IDENT.fullmatch(name)))
        if labels:
            out.append(Function(library, module, area, tuple(place[k] for k in range(size)), labels))
    return out


def from_library(name: str, data: bytes) -> tuple[list[Function], list[str]]:
    """Patterns from an `ar` library or a single object, and the modules that couldn't be read (with why)."""
    members = ar_members(data) if data.startswith(b"!<arch>\n") else [(name, data)]
    out, skipped = [], []
    for member, body in members:
        try:
            out += parse_rel(body.decode("latin-1"), name, member)
        except (ValueError, UnicodeDecodeError) as exc:
            skipped.append(f"{member}: {exc}")
    return out, skipped


def c_name(symbol: str) -> str:
    """SDCC writes a C name with one more leading underscore (`_memcpy`, `__mulint` for `_mulint`)."""
    return symbol[1:] if symbol.startswith("_") and len(symbol) > 1 else symbol


def _anchor(pattern) -> tuple[bytes, int]:
    best, best_at, run, run_at = b"", 0, bytearray(), 0
    for i, value in enumerate((*pattern, None)):
        if value is not None:
            if not run:
                run_at = i
            run.append(value)
        else:
            if len(run) > len(best):
                best, best_at = bytes(run), run_at
            run.clear()
    return best, best_at


def strong(function: Function) -> bool:
    """Long and concrete enough that a unique hit is meaningful."""
    return len(function.pattern) >= MIN_LENGTH and sum(v is not None for v in function.pattern) >= MIN_CONCRETE \
        and len(_anchor(function.pattern)[0]) >= MIN_ANCHOR


def scan(image: bytes, functions: list[Function], seconds: float = 60) -> dict:
    """Unique whole-pattern hits by ROM offset: every label of a hit, conflicts where libraries disagree on a name."""
    deadline = time.monotonic() + seconds
    usable = [f for f in functions if strong(f)]
    seen: dict[tuple, Function] = {}
    for function in usable:  # the same code in several libraries (z80.lib, sms.lib) is one pattern
        seen.setdefault((function.pattern, function.labels), function)
    labels: dict[int, dict[str, dict]] = {}
    truncated = False
    for (pattern, _labels), function in seen.items():
        if time.monotonic() >= deadline:
            truncated = True
            break
        anchor, anchor_at = _anchor(pattern)
        at, found, ambiguous = 0, None, False
        while (hit := image.find(anchor, at)) >= 0:
            at, start = hit + 1, hit - anchor_at
            if start < 0 or start + len(pattern) > len(image):
                continue
            if all(v is None or image[start + i] == v for i, v in enumerate(pattern)):
                if found is not None:
                    ambiguous = True
                    break
                found = start
        if found is None or ambiguous:
            continue
        for name, offset in function.labels:
            entry = labels.setdefault(found + offset, {}).setdefault(name, {"libraries": set(), "modules": set(), "end": 0})
            entry["libraries"].add(function.library)
            entry["modules"].add(function.module)
            entry["end"] = max(entry["end"], found + len(pattern))
    hits, conflicts = [], []
    for offset, names in sorted(labels.items()):
        # Names one module defines at the same place are aliases (`___memcpy` and `_memcpy`); others conflict.
        if len(names) > 1 and not set.intersection(*(e["modules"] for e in names.values())):
            conflicts.append({"rom_offset": offset, "names": sorted(names)})
            continue
        symbol = min(names, key=lambda n: (len(n) - len(n.lstrip("_")), len(n), n))
        evidence = names[symbol]
        hits.append({"rom_offset": offset, "name": c_name(symbol), "symbol": symbol,
                     "aliases": sorted(set(names) - {symbol}), "matched_end": evidence["end"],
                     "libraries": sorted(evidence["libraries"]), "modules": sorted(evidence["modules"])})
    return {"hits": hits, "conflicts": conflicts, "patterns": len(seen), "weak_skipped": len(functions) - len(usable),
            "truncated": truncated,
            "note": "Library evidence names library functions; the game's own code may use another compiler."}
