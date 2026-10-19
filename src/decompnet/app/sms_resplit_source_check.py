"""Mechanical checks of retained SMS/GG source against a proposed, immutable split layout."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass

from ..compiler import SourceRejected
from ..project import compiler_settings
from ..rom import gb_build, sms_asm, sms_profile
from ..rom.sms_mapping import Mapper, rom_coordinate

SOURCE_BYTES = 65536


@dataclass(frozen=True)
class Result:
    state: str
    kind: str
    problems: tuple[str, ...] = ()
    source: str = ""

    def report(self):
        return {"state": self.state, "kind": self.kind, "problems": list(self.problems),
                "scope": "assembly-byte-and-placement" if self.kind == "asm" else "function-byte-reference"}


def check(before: dict, row: dict, candidate, names: dict[int, str], functions, regions, *, timeout: float = 5) -> Result:
    """No database writes, source rewriting, original-compiler assertion or semantic-purpose approval."""
    kind = "asm" if row["status"] == "documented" else "c"
    source = row.get("matched_source") or ""

    def unresolved(reason):
        return Result("unresolved", kind, (reason,), source)

    if not source or len(source.encode()) > SOURCE_BYTES:
        return unresolved("accepted source is missing or exceeds the 64 KiB revalidation budget")
    cfg = json.loads(before["project"]["config"])
    view = sms_profile.describe(cfg)
    if not view or not view["supported"]:
        return unresolved("source revalidation needs a supported cartridge declaration")
    model = Mapper(view["profile"]["mapper"], cfg["rom"]["size"])
    if rom_coordinate(model, candidate.rom // 0x4000, candidate.vram).rom_offset != candidate.rom:
        return unresolved("proposed CPU/physical coordinate is not established cartridge ROM")
    symbols = {r["name"]: r["address"] for r in before["tables"]["symbols"]}
    symbols.update({names[fn.rom]: fn.vram for fn in functions})
    # A legacy function alias without a proposed entry coordinate is not evidence of a ROM target.
    proposed_names = set(names.values())
    missing = {r["name"] for r in before["tables"]["functions"] if r["name"] not in proposed_names}
    if missing & set(re.findall(r"[A-Za-z_]\w*", source)):
        return unresolved("retained source references a function without a proposed entry coordinate")
    if kind == "asm":
        if not sms_asm.available():
            return unresolved("WLA-DX is unavailable; retained source remains unaccepted")
        routine = sms_asm.Routine(names[candidate.rom], candidate.rom // 0x4000, candidate.vram, candidate.code,
            symbols, {fn.rom: names[fn.rom] for fn in functions}, {fn.rom: fn.vram for fn in functions},
            [(lo, count, kind) for lo, count, kind, *_ in regions],
            max(1, -(-model.size // 0x4000)), mapper=model.kind, rom_size=model.size)
        try:
            verdict = sms_asm.judge(routine, source, timeout=timeout)
        except (OSError, sms_asm.AsmError):
            return unresolved("assembly tools could not complete source revalidation")
        if any('timed out' in problem or 'time budget' in problem for problem in verdict.problems):
            return unresolved('assembly source revalidation exceeded its time budget')
        categories = {"1": "byte equality/build", "2": "address placement", "3": "ROM mapping",
                      "4": "instruction/data layout", "5": "hardware names", "6": "source documentation"}
        problems = tuple(sorted({categories.get(problem[:1], "source syntax/structure") for problem in verdict.problems}))
        return Result("passed" if verdict.ok else "failed", kind, problems,
                      verdict.text if verdict.ok else source)
    if not gb_build.available("z80"):
        return unresolved("GBDK/SDCC is unavailable; retained C remains an unaccepted reference")
    selected = compiler_settings(cfg, row.get("unit") or "")
    if selected.get("include_dirs"):
        return unresolved("compiler include inputs need a captured dependency context before automatic revalidation")
    contexts = [r for r in before["tables"]["context_versions"] if r["unit"] in (row.get("unit") or "", "")]
    context = max(contexts, key=lambda r: (r["unit"] == (row.get("unit") or ""), r["version"]), default=None)
    try:
        flags = selected.get("flags")
        built = gb_build.compile_function(source, names[candidate.rom], context_header=context["header"] if context else "",
                                          symbols=symbols, arch="z80", timeout=timeout,
                                          **({} if flags is None else {"opt": list(flags)}))
    except (gb_build.RomError, SourceRejected) as exc:
        if 'timed out' in str(exc):
            return unresolved('C source revalidation exceeded its time budget')
        return Result("failed", kind, ("retained C could not be built under the current compiler/context",), source)
    except OSError:
        return unresolved("compiler tools could not complete source revalidation")
    if built.code != candidate.code:
        return Result("failed", kind, ("compiled C bytes differ from the proposed target",), source)
    return Result("passed", kind, source=source)
