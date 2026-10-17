"""Nintendo Entertainment System / Famicom (.nes) ROMs: the iNES and NES 2.0 header, a banking model for the common
mappers, and function discovery on top of the fork's own 6502 decoder (`mos6502.py`).

What it covers: reading, disassembly and function discovery, and with the pinned GBDK-2020 toolchain installed the
matching lane (`gb_build` with `arch="mos6502"`: SDCC's 6502 back end, byte-compared against the ROM). Nearly every
commercial NES game was written in assembly, so the lane's real use is homebrew built with GBDK-2020 or SDCC; for
the rest this is a reader, a navigator and a scorer for attempts, not a promise of a match.

The file. An iNES file is a 16-byte header, an optional 512-byte trainer, the PRG ROM (the 6502's code and data, in
16 KiB units), then the CHR ROM (graphics). Only the PRG holds code. Every offset this module returns is an offset in
the *file* (header included), so it can be found in a hex editor; the banking maths runs on offsets within the PRG.

Banking. Which PRG bank the CPU sees at an address is set by writes to mapper registers, and that is not in the ROM,
so the model is the common arrangement of each mapper, the way the Game Boy lane shows its banks:
  * NROM (0), CNROM (3): the PRG at 0x8000 (a 16 KiB one is shown at 0xC000, where its vectors are, and mirrored at 0x8000).
  * MMC1 (1), UxROM (2), UNROM 512 (30), 94 and the many look-alikes: 16 KiB banks, the last one fixed at 0xC000, the
    others shown at 0x8000. (An unknown mapper is read this way too.)
  * Mapper 180: the first bank fixed at 0x8000, the others at 0xC000.
  * MMC3 (4, 118, 119): 8 KiB banks, the last two fixed at 0xC000 and 0xE000, the rest shown at 0x8000.
  * AxROM (7), GxROM (66), BNROM (34), 11, 79: 32 KiB banks at 0x8000.
The reset, NMI and IRQ vectors are the last six bytes of the PRG. A function's name spells its bank and CPU address
(`func_<bank>_<address>`), because two banks can hold code at the same address.

Function discovery is approximate by nature: the 6502 has no code/data separation, an indirect `jmp ($xxxx)` has no
visible target, and a game can dispatch through a table of addresses it pushes and returns to. The vectors are
followed through every `jsr` and `jmp`; `jsr` targets in code the descent never reached are kept when they read as a
function; and runs of three or more addresses (a handler table, or the address-minus-one form `rts` dispatch uses)
that each point at a function are taken as one.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from . import gb, mos6502
from .n64 import RomError

MAGIC = b"NES\x1a"
HEADER_SIZE = 16
TRAINER_SIZE = 512
PRG_UNIT = 0x4000
CHR_UNIT = 0x2000
MAX_FUNCTION = 0x1000  # a function longer than this is more likely a run of code the sweep never ended
MIN_TABLE = 3          # addresses in a row that make a handler table

#: mapper number -> (name, banking model). See the module docstring; anything not listed is read like UxROM.
MAPPERS: dict[int, tuple[str, str]] = {
    0: ("NROM", "nrom"), 1: ("MMC1", "last"), 2: ("UxROM", "last"), 3: ("CNROM", "nrom"),
    4: ("MMC3", "mmc3"), 5: ("MMC5", "last"), 7: ("AxROM", "all"), 9: ("MMC2", "last"), 10: ("MMC4", "last"),
    11: ("Color Dreams", "all"), 19: ("Namco 163", "last"), 21: ("VRC4", "last"), 22: ("VRC2", "last"),
    23: ("VRC2/4", "last"), 24: ("VRC6", "last"), 25: ("VRC4", "last"), 26: ("VRC6", "last"), 30: ("UNROM 512", "last"),
    34: ("BNROM", "all"), 66: ("GxROM", "all"), 69: ("FME-7", "last"), 71: ("Camerica", "last"), 79: ("NINA-03/06", "all"),
    94: ("UN1ROM", "last"), 118: ("TxSROM", "mmc3"), 119: ("TQROM", "mmc3"), 180: ("UNROM (reversed)", "first"),
    206: ("DxROM", "mmc3"),
}
_UNIT = {"nrom": PRG_UNIT, "last": PRG_UNIT, "first": PRG_UNIT, "mmc3": 0x2000, "all": 0x8000}


# ---------------------------------------------------------------- the header

def is_nes(data: bytes) -> bool:
    return len(data) >= HEADER_SIZE + 0x2000 and data[:4] == MAGIC


def parse_header(data: bytes) -> dict:
    """The iNES / NES 2.0 header as numbers. Raises RomError for a file this module cannot read."""
    if not is_nes(data):
        raise RomError("this isn't an NES ROM (no iNES header)")
    flags6, flags7 = data[6], data[7]
    nes2 = (flags7 & 0x0C) == 0x08
    # Old dumps have a tool's name in bytes 7-15 ("DiskDude!"): byte 7 is then not flags, and the mapper's high nibble is 0.
    dirty = not nes2 and any(data[12:16])
    mapper = (flags6 >> 4) | (0 if dirty else flags7 & 0xF0)
    prg_units, chr_units = data[4], data[5]
    submapper = 0
    if nes2:
        mapper |= (data[8] & 0x0F) << 8
        submapper = data[8] >> 4
        if data[9] & 0x0F == 0x0F or data[9] >> 4 == 0x0F:
            raise RomError("this NES 2.0 ROM states its size as an exponent, which isn't supported")
        prg_units |= (data[9] & 0x0F) << 8
        chr_units |= (data[9] >> 4) << 8
    trainer = bool(flags6 & 4)
    prg_off = HEADER_SIZE + (TRAINER_SIZE if trainer else 0)
    prg_size = prg_units * PRG_UNIT
    if prg_size == 0:
        raise RomError("this NES ROM has no program (the header says 0 PRG banks)")
    available = len(data) - prg_off
    truncated = available < prg_size
    if truncated:  # a cut-off dump: read what is there, whole 8 KiB at a time
        prg_size = available // 0x2000 * 0x2000
        if prg_size == 0:
            raise RomError("this NES ROM is cut off before its program ends")
    return {
        "mapper": mapper, "submapper": submapper, "nes2": nes2, "trainer": trainer,
        "prg_off": prg_off, "prg_size": prg_size, "prg_units": prg_units, "truncated": truncated,
        "chr_size": chr_units * CHR_UNIT, "battery": bool(flags6 & 2),
        "mirroring": "four-screen" if flags6 & 8 else "vertical" if flags6 & 1 else "horizontal",
        "region": ("PAL" if data[12] & 3 == 1 else "NTSC" if data[12] & 3 == 0 else "multi-region" if data[12] & 3 == 2
                   else "Dendy") if nes2 else ("PAL" if not dirty and data[9] & 1 else "NTSC"),
    }


def read_info(data: bytes, name: str = "") -> dict:
    """The cartridge header, in the shape the rest of the fork expects from a ROM reader."""
    h = parse_header(data)
    layout = layout_of(h)
    mapper_name = MAPPERS.get(h["mapper"], (f"mapper {h['mapper']}", "last"))[0]
    known = h["mapper"] in MAPPERS
    stem = Path(name).stem if name else ""
    prg_kb = h["prg_size"] // 1024
    chr_text = f"{h['chr_size'] // 1024} KiB CHR" if h["chr_size"] else "CHR RAM"
    return {
        "title": stem or "NES ROM",
        "game_code": "",
        "region": h["region"],
        "version": 0,
        "size": len(data),
        "sha1": hashlib.sha1(data).hexdigest(),
        "entrypoint": 0,
        "platform": "nes",
        "byte_order": "little",
        "compiler_guess": "a 6502 assembler, cc65 or SDCC (unknown)",
        "gp": 0,
        "header": True,
        "cartridge": f"{mapper_name}{'' if known else ' (read as UxROM)'} (mapper {h['mapper']}), {prg_kb} KiB PRG, "
                     f"{chr_text}, {h['mirroring']}{', battery' if h['battery'] else ''}",
        "rom_banks": layout.banks,
        "bank_size": layout.unit,
        "mapper": h["mapper"],
        "prg_offset": h["prg_off"],
        "prg_size": h["prg_size"],
        "chr_size": h["chr_size"],
        "nes2": h["nes2"],
        "truncated": h["truncated"],
    }


# ---------------------------------------------------------------- banking

@dataclass(frozen=True)
class Layout:
    """How a mapper shows the PRG to the CPU (see the module docstring)."""

    kind: str   # nrom | last | first | mmc3 | all
    unit: int   # the size of one bank
    size: int   # the PRG's size in bytes

    @property
    def banks(self) -> int:
        return max(1, -(-self.size // self.unit))

    def base(self, bank: int) -> int:
        """The CPU address where `bank` is shown."""
        if self.kind == "nrom":
            # a 16 KiB program is shown at 0xC000: its vectors are at 0xFFFA, so that is where its code is assembled
            return 0xC000 if self.size <= PRG_UNIT else 0x8000 + PRG_UNIT * bank
        if self.kind == "last":
            return 0xC000 if bank == self.banks - 1 else 0x8000
        if self.kind == "first":
            return 0x8000 if bank == 0 else 0xC000
        if self.kind == "mmc3":
            return 0xE000 if bank == self.banks - 1 else 0xC000 if bank == self.banks - 2 else 0x8000
        return 0x8000

    def bank_of(self, p: int) -> int:
        return p // self.unit

    def cpu(self, p: int) -> int:
        """The CPU address of the byte at PRG offset `p`."""
        return self.base(p // self.unit) + p % self.unit

    def target(self, cpu: int, from_bank: int) -> int | None:
        """The PRG offset a jump or call to `cpu` reaches from code in `from_bank`, or None for RAM, registers and
        addresses nothing is mapped at."""
        if cpu < 0x8000:
            return None
        n, unit, p = self.banks, self.unit, None
        if self.kind == "nrom":
            p = (cpu - 0x8000) % PRG_UNIT if self.size <= PRG_UNIT else cpu - 0x8000
        elif self.kind == "last":
            if cpu >= 0xC000:
                p = (n - 1) * unit + cpu - 0xC000
            elif n > 1:
                bank = from_bank if self.base(from_bank) == 0x8000 else 0
                p = bank * unit + cpu - 0x8000
        elif self.kind == "first":
            if cpu < 0xC000:
                p = cpu - 0x8000
            elif n > 1:
                bank = from_bank if self.base(from_bank) == 0xC000 else 1
                p = bank * unit + cpu - 0xC000
        elif self.kind == "mmc3":
            if cpu >= 0xE000:
                p = (n - 1) * unit + cpu - 0xE000
            elif cpu >= 0xC000 and n >= 2:
                p = (n - 2) * unit + cpu - 0xC000
            elif cpu >= 0xA000 and n >= 4:
                p = unit + cpu - 0xA000  # the second window: which bank is there is the game's choice; bank 1 is a guess
            elif cpu < 0xA000 and n >= 3:
                bank = from_bank if self.base(from_bank) == 0x8000 else 0
                p = bank * unit + cpu - 0x8000
        else:  # "all": the bank is the whole CPU window
            p = from_bank * unit + cpu - 0x8000
        return p if p is not None and 0 <= p < self.size else None


def layout_of(header: dict) -> Layout:
    kind = MAPPERS.get(header["mapper"], ("", "last"))[1]
    if kind == "nrom" and header["prg_size"] > 2 * PRG_UNIT:
        kind = "last"  # a CNROM header with more than 32 KiB of PRG isn't one
    return Layout(kind, _UNIT[kind], header["prg_size"])


def segments(info: dict) -> list[dict]:
    """The project's segments: one per PRG bank, at the CPU address the bank is shown at."""
    layout = Layout(layout_of({"mapper": info["mapper"], "prg_size": info["prg_size"]}).kind, info["bank_size"], info["prg_size"])
    off = info["prg_offset"]
    return [{"name": f"bank{b:03d}", "rom_start": off + b * layout.unit,
             "rom_end": off + min((b + 1) * layout.unit, layout.size), "vram": layout.base(b)}
            for b in range(layout.banks)]


def function_name(p: int, layout: Layout) -> str:
    return f"func_{layout.bank_of(p):03d}_{layout.cpu(p):04x}"


def vectors(prg: bytes, layout: Layout) -> dict[str, int]:
    """{"nmi" | "reset" | "irq": PRG offset}: the three vectors in the last six bytes of the PRG, for those that point
    into the ROM."""
    out: dict[str, int] = {}
    last = layout.banks - 1
    for i, name in enumerate(("nmi", "reset", "irq")):
        word = prg[len(prg) - 6 + 2 * i] | (prg[len(prg) - 5 + 2 * i] << 8)
        p = layout.target(word, last)
        if p is not None:
            out[name] = p
    return out


# ---------------------------------------------------------------- function discovery

def _walk(prg: bytes, layout: Layout, start: int, hard: int, starts: set[int]):
    """Walk the function that begins at PRG offset `start`: yield (offset, text, length) per instruction.

    It ends at a return or an unconditional jump once every forward branch seen so far has been passed, so a branch
    over a `jmp`, or a loop's back-edge, does not end it. A `jmp` is part of the function only when something before it
    already branches past it; otherwise nothing after it can be reached from here and it leaves the function (a tail
    call). It never runs past `hard`, `MAX_FUNCTION`, or the end of its bank."""
    bank = layout.bank_of(start)
    limit = start
    off = start
    end = min(hard, start + MAX_FUNCTION, (bank + 1) * layout.unit, len(prg))
    while off < end:
        text, ln = mos6502.decode(prg[off:off + 3], layout.cpu(off))
        yield off, text, ln
        nxt = off + max(1, ln)
        kind, target = mos6502.flow(text)
        if kind in ("ret", "jump") and nxt > limit:
            return
        if target is not None and kind in ("jump", "cjump"):
            flat = layout.target(target, bank)
            if flat is not None and flat > off and flat not in starts and flat < end:
                limit = max(limit, flat)
        off = nxt


def _extent(prg: bytes, layout: Layout, start: int, hard: int, starts: set[int]) -> bytes:
    """A function's bytes: from its start up to and including the instruction that ends it, never past `hard`.

    Exact extents matter for matching: a candidate compiled from C produces the function and nothing else."""
    end = start
    for off, _text, ln in _walk(prg, layout, start, hard, starts):
        end = off + max(1, ln)
    return prg[start:end]


def _clean(layout: Layout, start: int, code: bytes) -> int:
    """How many instructions `code` is if it reads as a function, else 0: no undefined opcode, no `brk` (which is what
    zero padding and empty data decode to, and which a game almost never executes on purpose), and it ends on a
    `rts`, `rti` or `jmp`."""
    if not code:
        return 0
    insns = list(mos6502.disassemble(code, layout.cpu(start)))
    if not insns or any(t.startswith(("db ", "brk")) for _a, t, _l in insns):
        return 0
    return len(insns) if mos6502.is_return(insns[-1][1]) else 0


def candidates(prg: bytes, layout: Layout, limit: int = 6000) -> dict[int, str]:
    """{PRG offset: how it was found} for every plausible function start: the vectors, then everything the code
    found calls or tail-jumps to (recursive descent), then `jsr` targets from code the descent never reached and
    handler tables, each kept only when what it points at reads as a function."""
    found: dict[int, str] = {}
    for name, p in vectors(prg, layout).items():
        found.setdefault(p, name)

    def follow(start: int) -> None:
        todo = [start]
        while todo and len(found) < limit:
            s = todo.pop()
            code = _extent(prg, layout, s, len(prg), set(found))
            bank = layout.bank_of(s)
            for _a, text, _ln in mos6502.disassemble(code, layout.cpu(s)):
                kind, target = mos6502.flow(text)
                if target is None or kind not in ("call", "jump", "cjump"):
                    continue
                flat = layout.target(target, bank)
                if flat is None or flat in found:
                    continue
                if kind == "call" or not (s <= flat < s + len(code)):
                    found[flat] = "call" if kind == "call" else "jump"
                    todo.append(flat)

    for p in list(found):
        follow(p)

    # `jsr` anywhere in the ROM: a call from code the descent never reached still names a function. One call to a short
    # run of bytes is as likely data that happens to contain 0x20, so it needs a second caller or a few instructions.
    sites: dict[int, int] = {}
    for bank in range(layout.banks):
        lo, hi = bank * layout.unit, min((bank + 1) * layout.unit, len(prg))
        for off in range(lo, hi - 2):
            if prg[off] == 0x20:
                flat = layout.target(prg[off + 1] | (prg[off + 2] << 8), bank)
                if flat is not None and flat not in found:
                    sites[flat] = sites.get(flat, 0) + 1
    for flat in sorted(sites):
        if flat in found or len(found) >= limit:
            continue
        n = _clean(layout, flat, _extent(prg, layout, flat, len(prg), set(found)))
        if n and (sites[flat] >= 2 or n >= 3):
            found[flat] = "call"
            follow(flat)

    # handler tables: three or more addresses in a row, each at a function (or, for `rts` dispatch, one past it)
    for bank in range(layout.banks):
        lo, hi = bank * layout.unit, min((bank + 1) * layout.unit, len(prg))
        for run in _address_runs(prg, layout, bank, lo, hi):
            _take_table(prg, layout, run, found, follow, limit)
    return dict(sorted(found.items()))


def _address_runs(prg: bytes, layout: Layout, bank: int, lo: int, hi: int):
    """Runs of at least MIN_TABLE 16-bit addresses stored one after another in [lo, hi), each pointing into the ROM at
    a byte that starts a valid instruction. Yields lists of the PRG offsets they point at. Both the address itself and
    the address plus one (what `rts` dispatch stores) are tried, at both byte alignments."""
    for plus in (0, 1):
        for parity in (0, 1):
            run: list[int] = []
            for off in range(lo + parity, hi - 1, 2):
                raw = prg[off] | (prg[off + 1] << 8)
                flat = layout.target(raw + plus, bank) if 0x8000 <= raw + plus <= 0xFFFF else None
                if flat is not None and mos6502.OPCODES.get(prg[flat]) is not None:
                    run.append(flat)
                    continue
                if len(run) >= MIN_TABLE:
                    yield run
                run = []
            if len(run) >= MIN_TABLE:
                yield run


def _take_table(prg, layout, run, found, follow, limit) -> None:
    """Keep a run of addresses as functions when most of them read as one."""
    good = [flat for flat in run if _clean(layout, flat, _extent(prg, layout, flat, len(prg), set(found)))]
    if len(good) < len(run) * 0.75:
        return
    for flat in good:
        if flat not in found and len(found) < limit:
            found[flat] = "table"
            follow(flat)


def refs_of(code: bytes, cpu: int, bank: int, layout: Layout) -> list[tuple[int, int, int]]:
    """(offset in the function, 10, CPU address) for every call and jump out of `code`, as the other lanes record them."""
    out: list[tuple[int, int, int]] = []
    for a, text, _ln in mos6502.disassemble(code, cpu):
        kind, target = mos6502.flow(text)
        if target is None or kind not in ("call", "jump", "cjump"):
            continue
        flat = layout.target(target, bank)
        if flat is not None and not (cpu <= target < cpu + len(code)):
            out.append((a - cpu, 10, target))
    return out


def functions(data: bytes, log=lambda *_: None) -> list[gb.GbFunction]:
    """Every discovered function, disassembled. (The record type is shared with the Game Boy lane.) Offsets in the
    result are file offsets."""
    h = parse_header(data)
    layout = layout_of(h)
    prg = data[h["prg_off"]:h["prg_off"] + h["prg_size"]]
    found = candidates(prg, layout)
    if not found:
        raise RomError("no code found in this NES ROM: the reset vector doesn't point into it")
    starts = sorted(found)
    known = set(starts)
    out: list[gb.GbFunction] = []
    for i, start in enumerate(starts):
        hard = starts[i + 1] if i + 1 < len(starts) else len(prg)
        code = _extent(prg, layout, start, hard, known)
        insns = list(mos6502.disassemble(code, layout.cpu(start)))
        if not insns:
            continue
        cpu, bank = layout.cpu(start), layout.bank_of(start)
        out.append(gb.GbFunction(name=function_name(start, layout), vram=cpu, rom=h["prg_off"] + start, bank=bank,
                                 code=code, n_insns=len(insns), asm=mos6502.asm_text(code, cpu, width=4),
                                 refs=refs_of(code, cpu, bank, layout)))
    log(f"found {len(out)} functions in {layout.banks} bank{'s' if layout.banks != 1 else ''} "
        f"({', '.join(f'{n} {layout.cpu(p):04x}' for n, p in vectors(prg, layout).items())})")
    return out


def split(path: Path, workdir: Path, log=lambda *_: None, report: dict | None = None) -> list[gb.GbFunction]:
    """A ROM file's functions. (`report` gets {"splitter": "built-in"}: there is no external tool for the 6502.)"""
    if report is not None:
        report["splitter"] = "built-in"
    data = Path(path).read_bytes()
    if not is_nes(data):
        raise RomError("this isn't an NES ROM")
    info = read_info(data, Path(path).name)
    log(f"NES: {info['cartridge']}")
    if info["mapper"] not in MAPPERS:
        log(f"mapper {info['mapper']} is not one this app knows: its banks are shown the way UxROM's are, which may put "
            "some at the wrong CPU address")
    if info["truncated"]:
        log("this ROM is shorter than its header says: reading what is there")
    return functions(data, log=log)
