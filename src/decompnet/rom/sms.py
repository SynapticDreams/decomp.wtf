"""Sega Master System (.sms) and Game Gear (.gg) ROMs: detection, header, banking and function discovery, on top of
the fork's own Z80 disassembler (see `z80.py` for why one is needed).

What it covers: reading, disassembly and function discovery, and with the pinned GBDK-2020 toolchain installed the
matching lane (`gb_build` with `arch="z80"`: SDCC's Z80 back end, byte-compared against the ROM).

Detection. A cartridge made by Sega carries a header at 0x7FF0 (0x3FF0 or 0x1FF0 in a ROM of 16 or 8 KiB) that
starts with `TMR SEGA`; its last byte names the region (3 and 4 are Master System, 5 to 7 Game Gear) and the size.
Plenty of ROMs have no header at all (early Japanese games, much homebrew), so a file named `.sms` or `.gg` with a
plausible size is accepted too. Dumps with a 512-byte copier header in front are stripped of it.

Banking. Sega cartridges fix only $0000-$03FF to bank 0; all three larger windows can page. Mapperless
cartridges use flat ROM wiring, with undeclared small-ROM mirroring left unresolved. CPU addresses and physical
ROM offsets are distinct. Discovery and reference checks use sms_mapping; section/display defaults never
establish a bank. Cold call scans, declared symbol coordinates and near-pointer tables are research seeds,
not execution or purpose evidence. Unknown project profiles retain an explicitly provisional Sega listing recipe.
"""

from __future__ import annotations

import bisect
import hashlib
import re
from pathlib import Path

from . import gb, sms_seeds, sms_trace, z80
from .n64 import RomError
from .sms_identity import strip_copier_header as strip_copier_header
from .sms_mapping import BusState, Mapper
from .sms_analysis import AnalysisLimits, Budget, Session, GAP_PASSES

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
    raw = data
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
        "cartridge": f"Unresolved mapper, {banks} bank{'s' if banks != 1 else ''}",
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
    from .sms_identity import identify

    info["identity"] = identify(raw, data, info)
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


def function_name(flat: int, size: int, cpu: int | None = None) -> str:
    """`func_<bank>_<address>`: the address the code runs at (`cpu`, as discovery found it), else the provisional display placement."""
    return f"func_{bank_of(flat):03d}_{(cpu_address(flat, size) if cpu is None else cpu):04x}"


def segment_vram(bank: int, size: int) -> int:
    return slot_base(bank, size)


def target_flat(cpu: int, from_bank: int, size: int, here: int | None = None, *,
                mapping: BusState | None = None, mapper: str = "sega") -> int | None:
    """Resolve a ROM reference from explicit mapping or conditional entry evidence.

    An entry establishes only its own CPU window. Display placement does not establish other banks;
    callers needing reset banks must supply that state explicitly. RAM, BIOS and unknown sources return None.
    """
    try:
        model = Mapper(mapper, size)
    except ValueError:
        return None
    if mapping is None:
        flat = from_bank * BANK_SIZE + (here & (BANK_SIZE - 1)) if here is not None else -1
        mapping = model.entry(flat, here if here is not None else -1)
    return model.resolve(cpu, mapping).rom_offset


def banks(data: bytes) -> list[bytes]:
    return [data[i:i + BANK_SIZE].ljust(BANK_SIZE, b"\0") for i in range(0, len(data), BANK_SIZE)]


# ---------------------------------------------------------------- function discovery

_LD_PAIR = re.compile(r"^ld (hl|de|bc), \$([0-9a-f]{4})$")
_PAIR_WRITES = (("hl", sms_trace._WRITES_HL), ("de", sms_trace._WRITES_DE), ("bc", sms_trace._WRITES_BC))


def _walk(data: bytes, start: int, cpu: int, hard: int, starts: set[int], inline: dict[int, int] | None = None, *,
          mapper: str = "sega"):
    """Walk the function that begins at flat offset `start`, running at CPU address `cpu`: yield (flat, text,
    length) per instruction.

    It ends at an unconditional return or jump once every forward branch seen so far has been passed, so a `ret nc`
    in the middle, the `ret` before an `else` branch's target or a loop's back-edge does not end it. An unconditional
    jump is part of the function only when something before it already branches past it (the `else` of an
    if/else); otherwise nothing after it can be reached from here and it leaves the function: a tail call, or the
    reset vector's `jp init`. A computed call (`ld de,.next / push de / jp (hl)`) comes back to the address it
    pushed, so the function goes on there. It never runs past `hard`, `MAX_FUNCTION`, the end of its bank or of the
    ROM. `inline` ({flat: count}): routines that read `count` bytes after their call; those bytes come as one
    (flat, "db", count)."""
    size = len(data)
    bank = bank_of(start)
    limit = start
    off = start
    end = min(hard, start + MAX_FUNCTION, size, (bank + 1) * BANK_SIZE)
    loaded: dict[str, int] = {}  # register pairs loaded with a constant, and what was pushed of them
    pushed = None
    while off < end:
        here = cpu + off - start
        text, ln = z80.decode(data[off:off + 4], here)
        yield off, text, ln
        nxt = off + max(1, ln)
        kind, target = z80.flow(text)
        if (m := _LD_PAIR.match(text)):
            loaded[m.group(1)] = int(m.group(2), 16)
        elif text.startswith("push "):
            pushed = loaded.get(text[5:])
        elif text in ("jp (hl)", "jp (ix)", "jp (iy)") and pushed is not None:
            back = target_flat(pushed, bank, size, here, mapper=mapper)
            if back is not None and off < back < end and back not in starts:
                limit = max(limit, back)
            pushed = None
        else:
            for pair, writes in _PAIR_WRITES:
                if writes.match(text):
                    loaded.pop(pair, None)
        if kind in ("ret", "jump") and nxt > limit:
            return
        if inline and kind == "call" and "," not in text and (n := inline.get(target_flat(target, bank, size, here, mapper=mapper))):
            if nxt + n <= end:
                yield nxt, "db", n
            nxt += n
        if target is not None and kind in ("jump", "cjump"):
            flat = target_flat(target, bank, size, here, mapper=mapper)
            if flat is not None and flat > off and flat not in starts and flat < end:
                limit = max(limit, flat)
        off = nxt


def _extent(data: bytes, start: int, cpu: int, hard: int, starts: set[int], inline: dict | None = None, *,
            mapper: str = "sega") -> bytes:
    """A function's bytes: from its start up to and including the instruction that ends it, never past `hard`.

    Exact extents matter for matching: a candidate compiled from C produces the function and nothing else."""
    end = start
    for off, _text, ln in _walk(data, start, cpu, hard, starts, inline, mapper=mapper):
        end = off + max(1, ln)
    return data[start:end]


def _clean(data: bytes, start: int, cpu: int, code: bytes) -> bool:
    """A real function decodes without undefined opcodes and ends on an instruction that leaves it."""
    if not code or code[:2] in (b"\x00\x00", b"\xff\xff"):
        return False
    last = None
    for _a, text, _ln in z80.disassemble(code, cpu):
        if text.startswith("db "):
            return False
        last = text
    return last is not None and z80.is_return(last)


def _code_like(data: bytes, bank: int) -> bool:
    """A bank that reads like code: Z80 code is full of `ret` and `call` (a bank of it has hundreds of each), a bank
    of graphics, maps or text a handful."""
    chunk = data[bank * BANK_SIZE:(bank + 1) * BANK_SIZE]
    return chunk.count(0xC9) + chunk.count(0xCD) >= max(48, len(chunk) // 256)


def _swept(data: bytes, bank: int, known: set[int], skip=None, *, mapper: str = "sega") -> dict[int, tuple[int, str]]:
    """Provisional call seeds without inventing source banks from section placement."""
    size, out = len(data), {}
    for flat, cpu in sms_seeds.call_targets(data, bank, Mapper(mapper, size), skip):
        if flat not in known and flat not in out and _clean(data, flat, cpu, _extent(data, flat, cpu, size, known, mapper=mapper)):
            out[flat] = (cpu, "call")
    return out


def candidates(data: bytes, limit: int = 4000, labels: dict | None = None,
               hints: dict | None = None, *, mapper: str | None = None, report: dict | None = None,
               limits: sms_trace.Limits | None = None,
               analysis_limits: AnalysisLimits | None = None) -> tuple[dict[int, tuple[int, str]], dict[int, int]]:
    """({flat offset: (CPU address it runs at, how it was found)}, {bank: CPU address its code runs at}).

    Reset and declared entries seed shared-model tracing. Cold scans resolve only unconditional wiring
    (Sega's fixed first KiB or flat mapperless ROM); they never borrow a displayed bank. Symbol/table coordinates
    preserve their declared CPU windows. Coverage supplies observed windows where available. The remaining
    function/extent heuristics are provisional; no candidate establishes a semantic purpose.
    """
    hints = hints or {}
    mapper = mapper if mapper is not None else hints.get("mapper", "sega")
    model = Mapper(mapper, len(data))  # reject unsupported explicit model requests rather than silently substituting
    if type(limit) is not int or not 1 <= limit <= 1_000_000:
        raise ValueError("candidate output limit must be between 1 and 1000000")
    budget = Budget(analysis_limits)
    session = Session(lambda account: sms_trace.Tracer(data, hints=hints, mapper=mapper,
                                                      limits=limits, budget=account), budget)
    size = len(data)
    seeds = {v: (v, "vector") for v in VECTORS if v < size}
    seeds.update({f: (cpu, "hint") for f, cpu in (hints.get("entries") or {}).items()
                  if f < size and (f not in seeds or seeds[f][0] != cpu)})
    if labels:
        seeds.update({f: c for f, c in sms_trace.sym_seeds(labels, data, mapper=mapper).items() if f not in seeds})
    cov = hints.get("coverage")
    in_data = _data_mask(size, list(hints.get("data") or []) + (cov.runs("read") if cov is not None else []))
    seeds.update({f: c for f, c in _swept(data, 0, set(seeds), in_data, mapper=mapper).items() if f not in seeds})
    tracer, found = session.follow(seeds)
    bases = dict(found.bank_base)
    for bank in range(1, -(-size // BANK_SIZE)):  # banks nothing was followed into: where they most likely run
        if bank not in bases and (base := tracer.default_base(bank)) is not None:
            bases[bank] = base
    handlers = {f: c for f, c in _hint_tables(data, hints, mapper=mapper).items() if f not in seeds}
    if cov is not None:  # where calls entered while the game ran, at the address its bank runs at
        handlers.update({f: (cpu, "ran") for f in sorted(cov.entries) if f not in seeds and f < size
                         and (cpu := _coverage_cpu(cov, f, mapper)) is not None})
    if handlers:  # (the tables corrections name, read in the banks their code was found running at)
        seeds.update(handlers)
        _, found = session.follow(seeds)
        bases = {**bases, **found.bank_base}
    more = dict(found.starts)
    code_banks = {flat // BANK_SIZE for flat in found.starts}
    for bank in range(1, -(-size // BANK_SIZE)):
        if budget.stopped:
            break
        if bank in code_banks or _code_like(data, bank):  # (in a bank of graphics or text, CD bytes aren't calls)
            more.update(_swept(data, bank, set(more), in_data, mapper=mapper))
    if len(more) > len(found.starts):
        _, found = session.follow({**more, **seeds})
        bases = {**bases, **found.bank_base}
    if cov is not None and not budget.stopped:  # code that ran but wasn't followed: where each run of it starts
        ran = {f: (cpu, "ran") for f in range(size) if cov.code[f] and (f == 0 or not cov.code[f - 1])
               and f not in found.code and f not in more and f not in seeds
               and (cpu := _coverage_cpu(cov, f, mapper)) is not None}
        if ran:
            more.update(ran)
            _, found = session.follow({**more, **seeds})
            bases = {**bases, **found.bank_base}
    # code nothing points at (called through pointers kept in RAM, which this can't follow): what starts right where
    # a function ends, in a bank that has code, and reads like a function, is the next one. While that finds more.
    seeds = {**more, **seeds}
    for _ in range(GAP_PASSES):
        if budget.stopped:
            break
        gaps = _after_functions(data, found.starts, _inline(hints, found), mapper=mapper)
        if not gaps:
            break
        seeds.update(gaps)
        _, found = session.follow(seeds)
        bases = {**bases, **found.bank_base}
    else:
        if not budget.stopped and _after_functions(data, found.starts, _inline(hints, found), mapper=mapper):
            budget.note("gap discovery pass budget exhausted")
    starts = dict(sorted(found.starts.items())[:limit])
    summary = session.report(found, model, limit)
    if report is not None:
        report.update(summary)
        declared = hints.get("inline") or {}
        report["inline_inferred"] = [{"rom_offset": flat, "count": n}
                                     for flat, n in sms_trace.inferred_inline(found).items() if flat not in declared]
    return starts, bases


def _inline(hints: dict, found) -> dict[int, int]:
    """Operands read after a call: what corrections declare, else what evaluated calls established."""
    return {**sms_trace.inferred_inline(found), **(hints.get("inline") or {})}


def _data_mask(size: int, spans: list[tuple[int, int]]):
    """`flat -> bool` for bytes in `spans` ((flat, size) each), or None when there are none."""
    if not spans:
        return None
    mask = bytearray(size)
    for a, n in spans:
        mask[a:a + n] = b"\x01" * max(0, min(n, size - a))
    return lambda flat: 0 <= flat < size and mask[flat] == 1


def _coverage_cpu(cov, flat: int, mapper: str) -> int | None:
    observed = cov.cpus.get(flat)
    if observed:
        return next(iter(observed)) if len(observed) == 1 else None
    return flat if mapper == "mapperless" else None  # byte-indexed CDL does not establish a Sega CPU window


def _hint_tables(data: bytes, hints: dict, *, mapper: str = "sega") -> dict[int, tuple[int, str]]:
    return {flat: (cpu, "hint") for flat, cpu in sms_seeds.table_targets(
        data, hints.get("tables") or [], hints.get("table_cpus") or {}, Mapper(mapper, len(data)))}


def _after_functions(data: bytes, starts: dict[int, tuple[int, str]], inline: dict | None = None, *,
                     mapper: str = "sega") -> dict[int, tuple[int, str]]:
    """{flat: (cpu, "after")} for plausible function starts right where a function ends, where no function starts
    yet and no function's bytes run on. (`inline`: routines that read bytes after their call, as for _walk.)"""
    size, order = len(data), sorted(starts)
    known = set(order)
    spans = []
    for i, start in enumerate(order):
        cpu = starts[start][0]
        hard = order[i + 1] if i + 1 < len(order) else size
        spans.append((start, start + len(_extent(data, start, cpu, hard, known, inline, mapper=mapper)), cpu))
    out = {}
    for k, (start, end, cpu) in enumerate(spans):
        if end == start or end in known or end % BANK_SIZE == 0 or end >= size:
            continue
        if k + 1 < len(spans) and spans[k + 1][0] < end:
            continue  # (the next function starts inside this one's bytes)
        here = cpu + (end - start)
        if sms_trace.plausible(data, end, here):
            out[end] = (here, "after")
    return out


def _instructions(code: bytes, cpu: int, operands: dict | None = None):
    """(address, text, length) of the instructions in `code`, leaving out `operands` ({address: length})."""
    off = 0
    while off < len(code):
        addr = cpu + off
        if operands and (n := operands.get(addr)):
            off += n
            continue
        text, ln = z80.decode(code[off:off + 4], addr)
        yield addr, text, ln
        off += max(1, ln)


def refs_of(code: bytes, cpu: int, bank: int, size: int, operands: dict | None = None, *,
            mapper: str = "sega") -> list[tuple[int, int, int]]:
    """(offset in the function, 10, CPU address) for every call and jump out of `code`, as the other lanes record
    them (not in `operands`, {address: length}: bytes after a call that aren't instructions)."""
    out: list[tuple[int, int, int]] = []
    for a, text, _ln in _instructions(code, cpu, operands):
        kind, target = z80.flow(text)
        if target is None or kind not in ("call", "jump", "cjump"):
            continue
        flat = target_flat(target, bank, size, a, mapper=mapper)
        if flat is not None and 0 <= flat < size and not (cpu <= target < cpu + len(code)):
            out.append((a - cpu, 10, target))
    return out


def functions(data: bytes, log=lambda *_: None, labels: dict | None = None,
              report: dict | None = None, seeds: dict | None = None, hints: dict | None = None, *,
              mapper: str | None = None, limits: sms_trace.Limits | None = None,
              analysis_limits: AnalysisLimits | None = None) -> list[gb.GbFunction]:
    """Every discovered function, disassembled at the address it runs at. (The record type is shared with the Game
    Boy lane.) `labels` ({(bank, address): name}, from a symbol file) name what they label, and with `seeds` (the
    same, with the file's automatic names too) say where code starts; `report` gets {"bank_base": {bank: CPU
    address}} for the banks whose code was found running somewhere, and {"regions": [(flat, size, kind, why)]} for
    what isn't code. `hints`: the project's corrections, as engine._hints gives them: {"entries": {flat: cpu},
    "data": [(flat, count)], "tables": [(flat, count)], "inline": {flat: count}, "noreturn": {flat}}, and "platform"
    ("gg": a Game Gear cartridge in its own mode, whose ports $00-$06 aren't memory control). `report` also gets
    "inline_inferred": [{"rom_offset", "count"}], routines found to read operands after their calls."""
    hints = hints or {}
    report = report if report is not None else {}
    mapper = mapper if mapper is not None else hints.get("mapper", "sega")
    found, bases = candidates(data, labels=seeds if seeds is not None else labels, hints=hints, mapper=mapper,
                              report=report, limits=limits, analysis_limits=analysis_limits)
    if reasons := report["analysis_limits"]["exhausted"]:
        log("static discovery is incomplete: " + ", ".join(reasons))
    if exhausted := report["analysis_exhausted"]:
        log(f"static tracing reached a budget in {len(exhausted)} entries; discovery and mapper effects remain incomplete")
        for row in exhausted[:10]:
            log(f"ROM offset {row['rom_offset']:x}: {', '.join(row['reasons'])}")
    if unresolved := report["analysis_unresolved"]:
        log(f"execution effects remain unresolved in {len(unresolved)} entries")
        for row in unresolved[:10]:
            log(f"ROM offset {row['rom_offset']:x}: {', '.join(row['reasons'])}")
    if not found:
        raise RomError("no code found in this ROM: every candidate address pointed outside it")
    size = len(data)
    cov = hints.get("coverage")
    read = cov.runs("read") if cov is not None else []
    spans = sorted(list(hints.get("data") or []) + read)
    in_data = _data_mask(size, spans) or (lambda _flat: False)
    span_starts = [a for a, _n in spans]
    starts = sorted(f for f in found if not in_data(f))
    known = set(starts)
    declared = hints.get("inline") or {}
    inferred = {row["rom_offset"]: row["count"] for row in report.get("inline_inferred") or []}
    inline = {**inferred, **declared}
    regions = [(a, n, "hint", "a correction says these bytes aren't code") for a, n in hints.get("data") or []]
    regions += [(a, n, "read", "read as data while the game ran (coverage)") for a, n in read]
    taken: set[str] = set()
    out: list[gb.GbFunction] = []
    for i, start in enumerate(starts):
        cpu = found[start][0]
        hard = starts[i + 1] if i + 1 < len(starts) else min(start + MAX_FUNCTION, size)
        k = bisect.bisect_right(span_starts, start)  # (a function stops where data starts)
        hard = min(hard, span_starts[k]) if k < len(span_starts) else hard
        steps = list(_walk(data, start, cpu, hard, known, inline, mapper=mapper))
        code = data[start:steps[-1][0] + max(1, steps[-1][2])] if steps else b""
        operands = {cpu + off - start: n for off, text, n in steps if text == "db"}  # (CPU address: length)
        for (_at, call, _ln), (off, text, n) in zip(steps, steps[1:]):
            if text == "db":
                callee = target_flat(z80.flow(call)[1], bank_of(start), size, cpu + _at - start, mapper=mapper)
                regions.append((off, n, "inline", "read by the routine called just before" if callee in declared else
                                "read by the routine called just before: each evaluated call returned past them"))
        insns = list(_instructions(code, cpu, operands))
        if not insns:
            continue
        label = (labels or {}).get((bank_of(start), cpu))
        name = label if label and label not in taken and re.fullmatch(r"[A-Za-z_]\w*", label) else \
            function_name(start, size, cpu)
        taken.add(name)
        out.append(gb.GbFunction(name=name, vram=cpu, rom=start, bank=bank_of(start), code=code,
                                 n_insns=len(insns),
                                 asm=z80.asm_text(code, cpu, width=4, data=operands),
                                 refs=refs_of(code, cpu, bank_of(start), size, operands, mapper=mapper)))
    if report is not None:
        report["bank_base"] = bases
        if regions:
            report["regions"] = regions
    moved = sorted(b for b, base in bases.items() if base != slot_base(b, size))
    log(f"found {len(out)} functions in {-(-size // BANK_SIZE)} banks"
        + (f"; code in bank{'s' if len(moved) > 1 else ''} {', '.join(map(str, moved))} runs at the address the "
           "discovery established instead of the display default" if moved else ""))
    return out


def split(path: Path, workdir: Path, log=lambda *_: None, report: dict | None = None,
          hints: dict | None = None, *, symbol_layout: dict | None = None) -> list[gb.GbFunction]:
    """A ROM file's functions. (`report` gets {"splitter": "built-in"}: there is no external tool for the Z80, and
    the banks' addresses.) A symbol file next to the ROM (`game.sym` for `game.sms`) remains pending until declared;
    `hints` are the project's corrections (functions). `symbol_layout` opts into a revision-bound WLA declaration
    separating assembler banks/slots from physical 16 KiB banks. Its records/aliases are returned in the report;
    the original file is unchanged. Without a declaration, sidecar records remain unqualified suggestions."""
    if report is not None:
        report["splitter"] = "built-in"
    data = strip_copier_header(Path(path).read_bytes())
    if not is_sms(data, Path(path).name):
        raise RomError("this isn't a Master System or Game Gear ROM")
    info = read_info(data, Path(path).name)
    log(f"{info['platform'].upper()}: {info['title']} ({info['cartridge']}"
        f"{', header found' if info['header'] else ', no header'})")
    from .sms_symbol_sources import select

    imported = select(Path(path).with_suffix('.sym'), data, reference=(hints or {}).get('symbol_source'),
                      declaration=symbol_layout, mapper=(hints or {}).get('mapper', 'sega'), root=Path(workdir))
    labels, seeds = (imported.names, imported.seeds) if imported is not None else (None, None)
    if imported is not None:
        if report is not None:
            report['symbol_import'] = imported.report
        log(f"symbol source: {imported.report['state']}; {len(imported.seeds)} seed suggestions")
    if hints and any(hints.get(k) for k in ("entries", "data", "tables", "inline", "noreturn")):
        log("with the project's corrections")
    if hints and hints.get("coverage") is not None:
        log("with what an emulator saw the game run")
    hints = {"platform": info["platform"], **(hints or {})}  # (the project's own platform, when it says)
    return functions(data, log=log, labels=labels, report=report, seeds=seeds, hints=hints)
