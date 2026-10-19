"""Bounded preview of changed work and overlapping candidate coordinates, without stored source."""
import hashlib
import json

LIMIT = 100
OVERLAPS = 8


def plan_digest(before_digest: str, candidates, report: dict) -> str:
    plan = {"state": before_digest, "regions": report.get("regions"), "bank_base": report.get("bank_base"),
            "splitter": report.get("splitter"), "functions": [
                [fn.rom, fn.vram, hashlib.sha256(fn.code).hexdigest(), hashlib.sha256((fn.asm or "").encode()).hexdigest(),
                 fn.refs, getattr(fn, "edges", None)] for fn in candidates]}
    return hashlib.sha256(json.dumps(plan, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def describe(before: dict, candidates, kept: set[int]) -> dict:
    changed = [row for row in before["tables"]["functions"] if row["id"] not in kept]
    details = []
    for row in changed[:LIMIT]:
        low, size = row["rom_offset"], row["size"] or 0
        overlaps = [fn for fn in candidates if low is not None and low < fn.rom + len(fn.code) and fn.rom < low + size]
        details.append({"id": row["id"], "name": row["name"], "rom_offset": low, "cpu": row["vram"], "size": size,
                        "status": row["status"], "accepted_source": bool(row["matched_source"]),
                        "requires_revalidation": row["status"] in ("matched", "documented"),
                        "action": "retained" if row["status"] == "matched" else "archived",
                        "overlap_count": len(overlaps), "overlaps_truncated": len(overlaps) > OVERLAPS,
                        "overlaps": [{"rom_offset": fn.rom, "cpu": fn.vram, "size": len(fn.code)}
                                     for fn in overlaps[:OVERLAPS]]})
    return {"changed_work": details, "changed_work_count": len(changed), "changed_work_truncated": len(changed) > LIMIT,
            "history_retention": {key: len(before["tables"][key]) for key in ("functions", "attempts", "notes", "claims")}}
