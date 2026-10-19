"""Banked resplit preview/apply bookkeeping, separate from engine orchestration.

Discovery remains in each console lane. This module owns reconciliation of its results with
stored function work and annotations; preservation/history changes can be reviewed here.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

from ..network import NetworkError
from ..rom.symbols import AUTO_NAME
from . import banked_resplit_checks as checks, sms_resplit_revalidate as revalidate
from .banked_resplit_changes import describe, plan_digest
from . import banked_resplit_history as history, banked_resplit_state as snapshots
from .banked_import import BANKED_TOOLS, segments, with_edges


def resplit(net, slug: str, apply: bool = False, log=print, *, expected_plan: str | None = None) -> dict:
    """Split a Game Boy, Master System or NES game again with this version's splitter, keeping the work done on
    it: a function whose start, address and bytes don't change keeps its row (name, status, attempts, notes);
    SMS/GG changed accepted source is revalidated; other lanes protect matched ranges. Notes on a function
    that goes move to the new function that covers its start (else to the project). Without `apply`, only says
    what would change."""
    from ..rom import gb, nes, sms

    proj = net._project(slug)
    cfg = net.cfg(proj)
    arch = (cfg.get("arch") or "").lower()
    if expected_plan is not None and (not isinstance(expected_plan, str) or not re.fullmatch(r"[0-9a-f]{64}", expected_plan)):
        raise NetworkError("invalid resplit preview fingerprint")
    if expected_plan is not None and arch != "z80":
        raise NetworkError("resplit preview fingerprints are currently supported for SMS/GG")
    if arch not in BANKED_TOOLS or net.fork_slug(slug):
        raise NetworkError("splitting again is for Game Boy, Master System and NES projects")
    if slug in net.links:
        raise NetworkError("a room member's copy follows its host's split: the host splits again")
    root = Path(proj["root"])
    rom_path = root / cfg["rom"]["file"]
    if not rom_path.is_file():
        raise NetworkError(f"the project's copy of the game ({cfg['rom']['file']}) isn't in its folder any more")
    lane = sms if arch == "z80" else nes if arch == "mos6502" else gb
    checks.verify_input(arch, rom_path, cfg)
    before = history.capture(net, proj) if arch == "z80" else None
    before_digest = snapshots.encode(before)[1] if before is not None else None
    if apply and before is not None:
        checks.quiet(net, slug)
    report: dict = {}
    fns = lane.split(rom_path, root, log=log, report=report, hints=net._hints(proj))
    checks.verify_input(arch, rom_path, cfg)
    checks.verify_settings(cfg, net.cfg(net._project(slug)))
    if before is not None:
        history.unchanged(net, proj, before_digest)
    old = before["tables"]["functions"] if before is not None else \
        net.store.all("SELECT * FROM functions WHERE project_id=?", proj["id"])
    by_off = {r["rom_offset"]: r for r in old if r["rom_offset"] is not None}
    kept, fresh = set(), []
    for f in fns:
        r = by_off.get(f.rom)
        if r is not None and r["vram"] == f.vram and bytes(r["target"] or b"") == f.code:
            kept.add(r["id"])
        else:
            fresh.append(f)
    held = [(r["rom_offset"], r["rom_offset"] + (r["size"] or 0)) for r in old
            if before is None and r["status"] == "matched" and r["id"] not in kept and r["rom_offset"] is not None]
    fresh = [f for f in fresh if not any(lo < f.rom + len(f.code) and f.rom < hi for lo, hi in held)]
    gone = [r for r in old if r["id"] not in kept and (before is not None or r["status"] != "matched")]
    if before is not None:
        noted = {row["function_id"] for row in before["tables"]["notes"]} & {row["id"] for row in gone}
    else:
        noted = {r["id"] for r in gone if net.store.one("SELECT 1 FROM notes WHERE function_id=?", r["id"])}
    regions = [r for r in report.get("regions") or []
               if not any(lo < r[0] + r[1] and r[0] < hi for lo, hi in held)]  # a matched function keeps its bytes
    out = {"before": len(old), "after": len(kept) + len(held) + len(fresh), "kept": len(kept),
           "matched_kept": len([r for r in old if r["status"] == "matched" and (before is None or r["id"] in kept)]), "added": len(fresh),
           "removed": len(gone), "notes_moved": len(noted), "bank_base": report.get("bank_base", {}),
           "analysis_exhausted": report.get("analysis_exhausted", []),
           "analysis_unresolved": report.get("analysis_unresolved", []),
           "analysis_limits": report.get("analysis_limits", {}),
           "data_before": net.store.one("SELECT COALESCE(SUM(size), 0) AS n FROM data_regions WHERE project_id=?",
                                         proj["id"])["n"],
           "data_after": sum(r[1] for r in regions),
           "bytes_before": sum(r["size"] or 0 for r in old),
           "bytes_after": sum((r["size"] or 0) for r in old if r["id"] in kept or (before is None and r["status"] == "matched"))
           + sum(f.size for f in fresh),
           "corrections": net.store.one("SELECT COUNT(*) AS n FROM corrections WHERE project_id=? AND undone_at IS "
                                         "NULL", proj["id"])["n"]}
    if before is not None:
        out.update(describe(before, fns, kept))
        out.update(revalidate.preview(before, fns, regions))
        out["plan"] = plan_digest(before_digest, fns, report)
        if apply and expected_plan is not None and expected_plan != out["plan"]:
            raise NetworkError("resplit preview is stale; preview again before applying")
    proposed_names = revalidate.names_for(old, fns, kept) if before is not None else {}
    if not apply:
        return out
    changed_ids = {r['id'] for r in gone}
    if before is not None:
        changed_ids.update(row['id'] for row in revalidate.affected(before, fns, regions))
    if before is not None and any(row["function_id"] in changed_ids and row["expires_at"] > time.time()
                                  for row in before["tables"]["claims"]):
        raise NetworkError("release claims on changed functions before applying this resplit")
    results = revalidate.prepare(before, fns, regions, proposed_names) if before is not None else {}
    if before is not None:
        out.update(revalidate.report(results))
        out['matched_kept'] -= sum(row['status'] == 'matched' and row['id'] in kept and
                                  results[row['id']].state != 'passed' for row in old if row['id'] in results)
    spans = [(f.rom, f.rom + len(f.code), f) for f in fresh] + [
        (r["rom_offset"], r["rom_offset"] + (r["size"] or 0), r) for r in old if r["id"] in kept or (before is None and r["status"] == "matched")]
    names = {r["name"] for r in old if r["id"] in kept or (before is None and r["status"] == "matched")}
    renamed = {r["rom_offset"]: r["name"] for r in gone if not AUTO_NAME.match(r["name"])}
    # matched C (and documented assembly) calls functions by name: one that goes keeps its name as a symbol (its
    # address is still the routine's), or those matches would stop compiling
    used = "\n".join(r["matched_source"] or "" for r in old if r["status"] in ("matched", "documented"))
    with net.store.tx() as db:
        current = db.execute("SELECT config FROM projects WHERE id=?", (proj["id"],)).fetchone()
        if current is None:
            raise NetworkError("the project was removed during resplit")
        checks.verify_settings(cfg, json.loads(current["config"]))
        checks.verify_input(arch, rom_path, cfg)
        if before is not None:
            checks.quiet(net, slug)
            history.unchanged(net, proj, before_digest)
        for r in gone:
            if before is not None:
                db.execute("DELETE FROM attempts WHERE function_id=?", (r["id"],))  # retained in private history
            db.execute("DELETE FROM claims WHERE function_id=?", (r["id"],))
            db.execute("DELETE FROM twin_misses WHERE function_id=?", (r["id"],))
            db.execute("DELETE FROM functions WHERE id=?", (r["id"],))
            if not re.search(rf"\b{re.escape(r['name'])}\b", used):
                db.execute("DELETE FROM symbols WHERE project_id=? AND name=?", (proj["id"], r["name"]))
        new_ids = {}
        for f in fresh:
            name = proposed_names.get(f.rom, renamed.get(f.rom, f.name))  # a name someone gave the function that started here stays
            if name in names:
                name = f"{f.name}_{f.rom:06x}" if f.name in names else f.name
            names.add(name)
            unit = by_off[f.rom]['unit'] if before is not None and f.rom in by_off else f"bank{f.bank:03d}"
            new_ids[f.rom] = db.execute(
                "INSERT INTO functions(project_id,name,size,n_insns,target,relocs,asm,seed,unit,vram,rom_offset,status,"
                "meta) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (proj["id"], name, f.size, f.n_insns, f.code, json.dumps([list(x) for x in f.refs or []]), f.asm,
                 None, unit, f.vram, f.rom, "open", with_edges(None, getattr(f, "edges", None)))).lastrowid
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
            offset = r["rom_offset"] if r["rom_offset"] is not None else -1
            owner = next((x for lo, hi, x in spans if lo <= offset < hi), None)
            fid = (new_ids.get(owner.rom) if hasattr(owner, "rom") else owner["id"]) if owner is not None else None
            db.execute("UPDATE notes SET function_id=? WHERE function_id=?", (fid, r["id"]))
        net._store_regions(db, proj["id"], regions)
        cfg["segments"] = segments(cfg.get("platform", ""), cfg["rom"], report)
        from ..rom import fingerprint

        cfg["built_with"] = fingerprint.identify(cfg.get("platform", ""), rom_path.read_bytes())
        cfg["splitter"] = report.get("splitter", cfg.get("splitter"))
        checks.verify_input(arch, rom_path, cfg)  # failure rolls back preceding function/region updates
        db.execute("UPDATE projects SET config=? WHERE id=?", (json.dumps(cfg), proj["id"]))
        if before is not None:
            revalidate.apply(db, old, new_ids, kept, results, before_digest)
            history.mark_sms(db, proj["id"])
            checks.verify_input(arch, rom_path, cfg)
            summary = {key: out[key] for key in ("before", "after", "kept", "added", "removed")}
            removed_ids = {row["id"] for row in gone}
            summary["archived_attempts"] = sum(row["function_id"] in removed_ids for row in before["tables"]["attempts"])
            summary['source_revalidation'] = out['source_revalidation']
            summary["archived_documented"] = sum(row["status"] == "documented" for row in gone)
            after = history.capture(net, net._project(slug))
            if after["inputs"] != before["inputs"]:
                raise NetworkError("analysis inputs changed during resplit; preview again")
            out["history_id"] = history.record(db, proj["id"], before, after, summary)
        net._event(db, proj["id"], None, "split", f"split again: {out['kept']} functions unchanged, {out['added']} "
                    f"new, {out['removed']} gone ({out['matched_kept']} matched kept)")
    for cache in (net._xrefs, net._ops, net._syms, net._roms, net._progress_cache):
        cache.pop(proj["id"], None)
    with net.twins._lock:
        net.twins._prints.pop(proj["id"], None)
    if before is None:
        net.twins.set_aside_asm(net._project(slug))  # other lanes retain their existing classification path
    log(f"split again: {out['after']} functions ({out['kept']} unchanged, {out['added']} new, {out['removed']} gone)")
    return out

