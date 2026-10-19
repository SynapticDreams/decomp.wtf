"""Bounded preview of changed work and overlapping candidate coordinates, without stored source."""
import hashlib
import json

LIMIT = 100
OVERLAPS = 8


def plan_digest(before_digest: str, candidates, report: dict, *, proposed=None) -> str:
    plan = {"state": before_digest, "regions": report.get("regions"), "bank_base": report.get("bank_base"),
            "splitter": report.get("splitter"), "functions": [
                [fn.rom, fn.vram, hashlib.sha256(fn.code).hexdigest(), hashlib.sha256((fn.asm or "").encode()).hexdigest(),
                 fn.refs, getattr(fn, "edges", None)] for fn in candidates]}
    if proposed is not None:
        plan['proposed_configuration'] = proposed
    return hashlib.sha256(json.dumps(plan, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def describe(before: dict, candidates, kept: set[int]) -> dict:
    changed = [row for row in before["tables"]["functions"] if row["id"] not in kept]
    details = [detail(row, candidates) for row in changed[:LIMIT]]
    return {"changed_work": details, "changed_work_count": len(changed), "changed_work_truncated": len(changed) > LIMIT,
            "history_retention": {key: len(before["tables"][key]) for key in ("functions", "attempts", "notes", "claims")}}


def overlapping(row, candidates):
    low, size = row['rom_offset'], row['size'] or 0
    return [fn for fn in candidates if low is not None and low < fn.rom + len(fn.code) and fn.rom < low + size]


def coordinate(fn):
    return {'rom_offset': fn.rom, 'cpu': fn.vram, 'size': len(fn.code)}


def identity(row):
    return {'id': row['id'], 'name': row['name'][:512], 'name_truncated': len(row['name']) > 512,
            'rom_offset': row['rom_offset'], 'cpu': row['vram'], 'size': row['size'] or 0,
            'status': row['status'], 'accepted_source': bool(row['matched_source'])}


def detail(row, candidates):
    overlaps = overlapping(row, candidates)
    return {**identity(row), 'requires_revalidation': row['status'] in ('matched', 'documented'), 'action': 'archived',
            'overlap_count': len(overlaps), 'overlaps_truncated': len(overlaps) > OVERLAPS,
            'overlaps': [coordinate(fn) for fn in overlaps[:OVERLAPS]]}
