"""Banked resplit preview/apply bookkeeping, separate from engine orchestration.

Discovery remains in each console lane. This module owns reconciliation of its results with
stored function work and annotations; preservation/history changes can be reviewed here.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from ..network import NetworkError
from ..rom.symbols import AUTO_NAME
from .banked_import import BANKED_TOOLS, segments, with_edges


def resplit(net, slug: str, apply: bool = False, log=print) -> dict:
    """Split a Game Boy, Master System or NES game again with this version's splitter, keeping the work done on
    it: a function whose start, address and bytes don't change keeps its row (name, status, attempts, notes);
    a matched function is never removed (new functions that would overlap it are left out); notes on a function
    that goes move to the new function that covers its start (else to the project). Without `apply`, only says
    what would change."""
    from ..rom import gb, nes, sms

    proj = net._project(slug)
    cfg = net.cfg(proj)
    arch = (cfg.get("arch") or "").lower()
    if arch not in BANKED_TOOLS or net.fork_slug(slug):
        raise NetworkError("splitting again is for Game Boy, Master System and NES projects")
    if slug in net.links:
        raise NetworkError("a room member's copy follows its host's split: the host splits again")
    root = Path(proj["root"])
    rom_path = root / cfg["rom"]["file"]
    if not rom_path.is_file():
        raise NetworkError(f"the project's copy of the game ({cfg['rom']['file']}) isn't in its folder any more")
    lane = sms if arch == "z80" else nes if arch == "mos6502" else gb
    report: dict = {}
    fns = lane.split(rom_path, root, log=log, report=report, hints=net._hints(proj))
    old = net.store.all("SELECT * FROM functions WHERE project_id=?", proj["id"])
    by_off = {r["rom_offset"]: r for r in old if r["rom_offset"] is not None}
    kept, fresh = set(), []
    for f in fns:
        r = by_off.get(f.rom)
        if r is not None and r["vram"] == f.vram and bytes(r["target"] or b"") == f.code:
            kept.add(r["id"])
        else:
            fresh.append(f)
    held = [(r["rom_offset"], r["rom_offset"] + (r["size"] or 0)) for r in old
            if r["status"] == "matched" and r["id"] not in kept and r["rom_offset"] is not None]
    fresh = [f for f in fresh if not any(lo < f.rom + len(f.code) and f.rom < hi for lo, hi in held)]
    gone = [r for r in old if r["id"] not in kept and r["status"] != "matched"]
    noted = {r["id"] for r in gone if net.store.one("SELECT 1 FROM notes WHERE function_id=?", r["id"])}
    regions = [r for r in report.get("regions") or []
               if not any(lo < r[0] + r[1] and r[0] < hi for lo, hi in held)]  # a matched function keeps its bytes
    out = {"before": len(old), "after": len(kept) + len(held) + len(fresh), "kept": len(kept),
           "matched_kept": len([r for r in old if r["status"] == "matched"]), "added": len(fresh),
           "removed": len(gone), "notes_moved": len(noted), "bank_base": report.get("bank_base", {}),
           "analysis_exhausted": report.get("analysis_exhausted", []),
           "analysis_unresolved": report.get("analysis_unresolved", []),
           "analysis_limits": report.get("analysis_limits", {}),
           "data_before": net.store.one("SELECT COALESCE(SUM(size), 0) AS n FROM data_regions WHERE project_id=?",
                                         proj["id"])["n"],
           "data_after": sum(r[1] for r in regions),
           "bytes_before": sum(r["size"] or 0 for r in old),
           "bytes_after": sum((r["size"] or 0) for r in old if r["id"] in kept or r["status"] == "matched")
           + sum(f.size for f in fresh),
           "corrections": net.store.one("SELECT COUNT(*) AS n FROM corrections WHERE project_id=? AND undone_at IS "
                                         "NULL", proj["id"])["n"]}
    if not apply:
        return out
    spans = [(f.rom, f.rom + len(f.code), f) for f in fresh] + [
        (r["rom_offset"], r["rom_offset"] + (r["size"] or 0), r) for r in old if r["id"] in kept or r["status"] == "matched"]
    names = {r["name"] for r in old if r["id"] in kept or r["status"] == "matched"}
    renamed = {r["rom_offset"]: r["name"] for r in gone if not AUTO_NAME.match(r["name"])}
    # matched C (and documented assembly) calls functions by name: one that goes keeps its name as a symbol (its
    # address is still the routine's), or those matches would stop compiling
    used = "\n".join(r["matched_source"] or "" for r in old if r["status"] in ("matched", "documented"))
    with net.store.tx() as db:
        for r in gone:
            db.execute("DELETE FROM claims WHERE function_id=?", (r["id"],))
            db.execute("DELETE FROM twin_misses WHERE function_id=?", (r["id"],))
            db.execute("DELETE FROM functions WHERE id=?", (r["id"],))
            if not re.search(rf"\b{re.escape(r['name'])}\b", used):
                db.execute("DELETE FROM symbols WHERE project_id=? AND name=?", (proj["id"], r["name"]))
        new_ids = {}
        for f in fresh:
            name = renamed.get(f.rom, f.name)  # a name someone gave the function that started here stays
            if name in names:
                name = f"{f.name}_{f.rom:06x}" if f.name in names else f.name
            names.add(name)
            new_ids[f.rom] = db.execute(
                "INSERT INTO functions(project_id,name,size,n_insns,target,relocs,asm,seed,unit,vram,rom_offset,status,"
                "meta) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (proj["id"], name, f.size, f.n_insns, f.code, json.dumps([list(x) for x in f.refs or []]), f.asm,
                 None, f"bank{f.bank:03d}", f.vram, f.rom, "open", with_edges(None, getattr(f, "edges", None)))).lastrowid
            db.execute("INSERT OR REPLACE INTO symbols(project_id,name,address,size,kind,preview) VALUES(?,?,?,?,?,?)",
                       (proj["id"], name, f.vram, f.size, "func", None))
        for f in fns:  # a function that stays: where its calls into the window go, as this split followed them
            r = by_off.get(f.rom)
            if r is not None and r["id"] in kept and (getattr(f, "edges", None) or "edges" in (r["meta"] or "")):
                db.execute("UPDATE functions SET meta=? WHERE id=?", (with_edges(r["meta"], f.edges), r["id"]))
            if r is not None and r["id"] in kept and f.asm and f.asm != r["asm"]:  # (the same bytes, read anew:
                # what follows a call is the routine's operands now, say)
                db.execute("UPDATE functions SET asm=?, n_insns=?, relocs=? WHERE id=?",
                           (f.asm, f.n_insns, json.dumps([list(x) for x in f.refs or []]), r["id"]))
        for r in gone:  # its notes go to whatever covers its start now
            if r["id"] not in noted:
                continue
            owner = next((x for lo, hi, x in spans if lo <= (r["rom_offset"] or -1) < hi), None)
            fid = (new_ids.get(owner.rom) if hasattr(owner, "rom") else owner["id"]) if owner is not None else None
            db.execute("UPDATE notes SET function_id=? WHERE function_id=?", (fid, r["id"]))
        net._store_regions(db, proj["id"], regions)
        cfg["segments"] = segments(cfg.get("platform", ""), cfg["rom"], report)
        from ..rom import fingerprint

        cfg["built_with"] = fingerprint.identify(cfg.get("platform", ""), rom_path.read_bytes())
        cfg["splitter"] = report.get("splitter", cfg.get("splitter"))
        db.execute("UPDATE projects SET config=? WHERE id=?", (json.dumps(cfg), proj["id"]))
        net._event(db, proj["id"], None, "split", f"split again: {out['kept']} functions unchanged, {out['added']} "
                    f"new, {out['removed']} gone ({out['matched_kept']} matched kept)")
    for cache in (net._xrefs, net._ops, net._syms, net._roms):
        cache.pop(proj["id"], None)
    with net.twins._lock:
        net.twins._prints.pop(proj["id"], None)
    net.twins.set_aside_asm(net._project(slug))  # the new functions, through the set-aside rules
    log(f"split again: {out['after']} functions ({out['kept']} unchanged, {out['added']} new, {out['removed']} gone)")
    return out

