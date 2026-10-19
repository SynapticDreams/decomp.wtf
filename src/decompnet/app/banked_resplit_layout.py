"""Plan banked function/range reconciliation without changing stored work."""
from dataclasses import dataclass


@dataclass
class Layout:
    by_offset: dict
    kept: set
    fresh: list
    gone: list
    noted: set
    regions: list
    summary: dict


def reconcile(net, proj, before, old, fns, report):
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
    return Layout(by_off, kept, fresh, gone, noted, regions, out)
