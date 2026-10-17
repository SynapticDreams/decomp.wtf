"""Sega Master System (.sms) and Game Gear (.gg) ROMs: detection, header, banking and function discovery, on top of
the fork's own Z80 disassembler (see `z80.py` for why one is needed).

What it covers: reading, disassembly and function discovery, and with the pinned GBDK-2020 toolchain installed the
matching lane (`gb_build` with `arch="z80"`: SDCC's Z80 back end, byte-compared against the ROM).

Detection. A cartridge made by Sega carries a header at 0x7FF0 (0x3FF0 or 0x1FF0 in a ROM of 16 or 8 KiB) that
starts with `TMR SEGA`; its last byte names the region (3 and 4 are Master System, 5 to 7 Game Gear) and the size.
Plenty of ROMs have no header at all (early Japanese games, much homebrew), so a file named `.sms` or `.gg` with a
plausible size is accepted too. Dumps with a 512-byte copier header in front are stripped of it.

Banking. The Sega mapper has three 16 KiB slots: slot 0 (0x0000) shows bank 0, slot 1 (0x4000) and slot 2 (0x8000)
show any bank, set by writes to 0xFFFE and 0xFFFF. Which bank is mapped when is not in the ROM, so the model here is
the power-on one: bank 0 at 0x0000, bank 1 at 0x4000, bank 2 at 0x8000 in a ROM of three banks or fewer; in a bigger
ROM every bank above 0 is shown in slot 1 (0x4000), the way the Game Boy lane shows its banks. A function's name
spells its bank and CPU address (`func_<bank>_<address>`), because two banks can hold code at the same address.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from . import gb, z80
from .n64 import RomError

BANK_SIZE = 0x4000
MAGIC = b"TMR SEGA"
HEADER_OFFSETS = (0x7FF0, 0x3FF0, 0x1FF0)
COPIER_HEADER = 0x200
MAX_SIZE = 0x400000  # the mapper addresses 4 MiB
REGIONS = {3: "SMS Japan", 4: "SMS Export", 5: "GG Japan", 6: "GG Export", 7: "GG International"}
SIZES = {0xA: 0x2000, 0xB: 0x4000, 0xC: 0x8000, 0xD: 0xC000, 0xE: 0x10000, 0xF: 0x20000,
         0x0: 0x40000, 0x1: 0x80000, 0x2: 0x100000}
PLATFORMS = {"sms": "Sega Master System", "gg": "Sega Game Gear"}
#: Where the CPU starts looking: the reset vector, the RST handlers (0x38 is also the interrupt), and the NMI.
VECTORS = tuple(range(0x00, 0x40, 0x08)) + (0x66,)
MAX_FUNCTION = 0x800  # a function longer than this is more likely a run of code the sweep never ended


def strip_copier_header(data: bytes) -> bytes:
    """Dumps from old copiers start with 512 bytes that are not part of the ROM."""
    if len(data) % BANK_SIZE == COPIER_HEADER and header_offset(data[COPIER_HEADER:]) is not None:
        return data[COPIER_HEADER:]
    return data


def header_offset(data: bytes) -> int | None:
    """Where the `TMR SEGA` header sits in this ROM, or None. The size decides the place: 0x7FF0 from 32 KiB up,
    0x3FF0 in a ROM of 16 KiB, 0x1FF0 in one of 8."""
    off = HEADER_OFFSETS[0] if len(data) >= 0x8000 else HEADER_OFFSETS[1] if len(data) >= 0x4000 else HEADER_OFFSETS[2]
    return off if len(data) >= off + 0x10 and data[off:off + 8] == MAGIC else None


def _size_ok(size: int) -> bool:
    return 0x2000 <= size <= MAX_SIZE and size % 0x2000 == 0


def platform_of(data: bytes, name: str = "") -> str | None:
    """"sms", "gg", or None when this is not one of their ROMs."""
    off = header_offset(data)
    if off is not None and _size_ok(len(data)):
        return "gg" if (data[off + 0xF] >> 4) >= 5 else "sms"
    ext = Path(name).suffix.lower()
    if ext in (".sms", ".gg") and _size_ok(len(data)):
        return ext[1:]
    return None


def is_sms(data: bytes, name: str = "") -> bool:
    return platform_of(strip_copier_header(data), name) is not None


def checksum(data: bytes, off: int) -> int:
    """The header's checksum: the sum of every byte below the 16-byte header, and of those after it up to the declared
    size (the header itself is left out), modulo 0x10000."""
    declared = SIZES.get(data[off + 0xF] & 0xF, len(data))
    size = min(declared, len(data))
    return (sum(data[:off]) + sum(data[off + 0x10:size])) & 0xFFFF


def _product(data: bytes, off: int) -> str:
    code = f"{data[off + 0xE] >> 4:x}{data[off + 0xD]:02x}{data[off + 0xC]:02x}"
    return code.lstrip("0") or "0" if code.isdigit() else ""  # a BCD number: anything else is not a product code


def read_info(data: bytes, name: str = "") -> dict:
    """The cartridge header, in the shape the rest of the fork expects from a ROM reader."""
    data = strip_copier_header(data)
    platform = platform_of(data, name)
    if platform is None:
        raise RomError("this isn't a Master System or Game Gear ROM")
    off = header_offset(data)
    stem = Path(name).stem if name else ""
    banks = -(-len(data) // BANK_SIZE)
    info = {
        "title": stem or PLATFORMS[platform] + " ROM",
        "game_code": "",
        "region": "unknown",
        "version": 0,
        "size": len(data),
        "sha1": hashlib.sha1(data).hexdigest(),
        "entrypoint": 0,
        "platform": platform,
        "byte_order": "little",
        "compiler_guess": "SDCC or a hand-written assembler (unknown)",
        "gp": 0,
        "header": off is not None,
        "cartridge": f"Sega mapper, {banks} bank{'s' if banks != 1 else ''}",
        "rom_banks": banks,
    }
    if off is not None:
        region = data[off + 0xF] >> 4
        declared = SIZES.get(data[off + 0xF] & 0xF)
        info.update({
            "game_code": _product(data, off),
            "region": REGIONS.get(region, f"unknown ({region})"),
            "version": data[off + 0xE] & 0xF,
            "header_offset": off,
            "rom_bytes_declared": declared,
            "size_mismatch": bool(declared and declared != len(data)),
            "checksum": f"0x{data[off + 0xA] | (data[off + 0xB] << 8):04x}",
            "checksum_ok": checksum(data, off) == (data[off + 0xA] | (data[off + 0xB] << 8)),
        })
    return info


# ---------------------------------------------------------------- banking

def bank_of(flat: int) -> int:
    return flat // BANK_SIZE


def slot_base(bank: int, size: int) -> int:
    """The CPU address where `bank` is shown: see the module docstring for the model."""
    if bank == 0:
        return 0x0000
    if bank == 2 and size <= 3 * BANK_SIZE:
        return 0x8000
    return 0x4000


def cpu_address(flat: int, size: int) -> int:
    return slot_base(bank_of(flat), size) + flat % BANK_SIZE


def function_name(flat: int, size: int) -> str:
    return f"func_{bank_of(flat):03d}_{cpu_address(flat, size):04x}"


def segment_vram(bank: int, size: int) -> int:
    return slot_base(bank, size)


def target_flat(cpu: int, from_bank: int, size: int) -> int | None:
    """The flat ROM offset a call or jump to `cpu` reaches from code in `from_bank`, or None for RAM and ports.

    Slot 0 is always bank 0. Slot 1 is the caller's own bank when that bank is shown there, else bank 1 (the
    power-on mapping); slot 2 is bank 2, or the caller's own bank when it is shown there."""
    if cpu < 0x4000:
        return cpu
    if cpu < 0x8000:
        bank = from_bank if slot_base(from_bank, size) == 0x4000 else 1
        return bank * BANK_SIZE + (cpu - 0x4000)
    if cpu < 0xC000:
        bank = from_bank if slot_base(from_bank, size) == 0x8000 else 2
        return bank * BANK_SIZE + (cpu - 0x8000)
    return None


def banks(data: bytes) -> list[bytes]:
    return [data[i:i + BANK_SIZE].ljust(BANK_SIZE, b"\0") for i in range(0, len(data), BANK_SIZE)]


# ---------------------------------------------------------------- function discovery

def _walk(data: bytes, start: int, hard: int, starts: set[int]):
    """Walk the function that begins at flat offset `start`: yield (flat, cpu_text, length) per instruction.

    It ends at an unconditional return or jump once every forward branch seen so far has been passed, so a `ret nc`
    in the middle, the `ret` before an `else` branch's target or a loop's back-edge does not end it. An unconditional
    jump is part of the function only when something before it already branches past it (the `else` of an
    if/else); otherwise nothing after it can be reached from here and it leaves the function: a tail call, or the
    reset vector's `jp init`. It never runs past `hard`, `MAX_FUNCTION`, or the end of the ROM."""
    size = len(data)
    bank = bank_of(start)
    limit = start
    off = start
    end = min(hard, start + MAX_FUNCTION, size)
    while off < end:
        text, ln = z80.decode(data[off:off + 4], cpu_address(off, size))
        yield off, text, ln
        nxt = off + max(1, ln)
        kind, target = z80.flow(text)
        if kind in ("ret", "jump") and nxt > limit:
            return
        if target is not None and kind in ("jump", "cjump"):
            flat = target_flat(target, bank, size)
            if flat is not None and flat > off and flat not in starts and flat < end:
                limit = max(limit, flat)
        off = nxt


def _extent(data: bytes, start: int, hard: int, starts: set[int]) -> bytes:
    """A function's bytes: from its start up to and including the instruction that ends it, never past `hard`.

    Exact extents matter for matching: a candidate compiled from C produces the function and nothing else."""
    end = start
    for off, _text, ln in _walk(data, start, hard, starts):
        end = off + max(1, ln)
    return data[start:end]


def _clean(data: bytes, start: int, code: bytes) -> bool:
    """A real function decodes without undefined opcodes and ends on an instruction that leaves it."""
    if not code:
        return False
    cpu = cpu_address(start, len(data))
    last = None
    for _a, text, _ln in z80.disassemble(code, cpu):
        if text.startswith("db "):
            return False
        last = text
    return last is not None and z80.is_return(last)


def candidates(data: bytes, limit: int = 4000) -> dict[int, str]:
    """{flat offset: how it was found} for every plausible function start.

    The reset vector, the RST handlers and the NMI are starts. From them, the calls and tail jumps of each function
    found are followed (recursive descent). On top of that every bank is swept for `call nn` and `rst`, the same
    union the Game Boy lane builds: calls made from code the descent never reached (a table of handlers, another
    bank) still name functions, kept only when what they point at reads as a function."""
    size = len(data)
    found: dict[int, str] = {}
    for v in VECTORS:
        if v < size:
            found.setdefault(v, "vector")

    def follow(start: int) -> None:
        todo = [start]
        while todo and len(found) < limit:
            s = todo.pop()
            hard = size  # the descent runs to the ROM's end; the final cut uses the next start
            code = _extent(data, s, hard, set(found))
            bank = bank_of(s)
            for _a, text, _ln in z80.disassemble(code, cpu_address(s, size)):
                kind, target = z80.flow(text)
                if target is None or kind not in ("call", "jump", "cjump"):
                    continue
                flat = target_flat(target, bank, size)
                if flat is None or not 0 <= flat < size or flat in found:
                    continue
                if kind == "call" or not (s <= flat < s + len(code)):
                    found[flat] = "call" if kind == "call" else "jump"
                    todo.append(flat)

    for v in list(found):
        follow(v)
    # a sweep of every bank for calls the descent never saw
    for bank in range(-(-size // BANK_SIZE)):
        lo, hi = bank * BANK_SIZE, min((bank + 1) * BANK_SIZE, size)
        for off in range(lo, hi - 2):
            op = data[off]
            if op in (0xCD, 0xC4, 0xCC, 0xD4, 0xDC, 0xE4, 0xEC, 0xF4, 0xFC):
                flat = target_flat(data[off + 1] | (data[off + 2] << 8), bank, size)
                if flat is not None and 0 <= flat < size and flat not in found:
                    if _clean(data, flat, _extent(data, flat, size, set(found))):
                        found[flat] = "call"
                        follow(flat)
            if len(found) >= limit:
                break
    return dict(sorted(found.items()))


def refs_of(code: bytes, cpu: int, bank: int, size: int) -> list[tuple[int, int, int]]:
    """(offset in the function, 10, CPU address) for every call and jump out of `code`, as the other lanes record them."""
    out: list[tuple[int, int, int]] = []
    for a, text, _ln in z80.disassemble(code, cpu):
        kind, target = z80.flow(text)
        if target is None or kind not in ("call", "jump", "cjump"):
            continue
        flat = target_flat(target, bank, size)
        if flat is not None and 0 <= flat < size and not (cpu <= target < cpu + len(code)):
            out.append((a - cpu, 10, target))
    return out


def functions(data: bytes, log=lambda *_: None) -> list[gb.GbFunction]:
    """Every discovered function, disassembled. (The record type is shared with the Game Boy lane.)"""
    found = candidates(data)
    if not found:
        raise RomError("no code found in this ROM: every candidate address pointed outside it")
    size = len(data)
    starts = sorted(found)
    known = set(starts)
    out: list[gb.GbFunction] = []
    for i, start in enumerate(starts):
        hard = starts[i + 1] if i + 1 < len(starts) else min(start + MAX_FUNCTION, size)
        code = _extent(data, start, hard, known)
        insns = list(z80.disassemble(code, cpu_address(start, size)))
        if not insns:
            continue
        cpu = cpu_address(start, size)
        out.append(gb.GbFunction(name=function_name(start, size), vram=cpu, rom=start, bank=bank_of(start), code=code,
                                 n_insns=len(insns), asm=z80.asm_text(code, cpu, width=4),
                                 refs=refs_of(code, cpu, bank_of(start), size)))
    log(f"found {len(out)} functions in {-(-size // BANK_SIZE)} banks")
    return out


def split(path: Path, workdir: Path, log=lambda *_: None) -> list[gb.GbFunction]:
    """A ROM file's functions."""
    data = strip_copier_header(Path(path).read_bytes())
    if not is_sms(data, Path(path).name):
        raise RomError("this isn't a Master System or Game Gear ROM")
    info = read_info(data, Path(path).name)
    log(f"{info['platform'].upper()}: {info['title']} ({info['cartridge']}"
        f"{', header found' if info['header'] else ', no header'})")
    return functions(data, log=log)
