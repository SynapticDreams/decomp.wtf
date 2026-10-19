"""Retained-source reconciliation against a frozen proposed SMS/GG layout, outside SQLite writes."""
from __future__ import annotations

import hashlib
import json
import time

from ..rom.symbols import AUTO_NAME
from ..project import compiler_settings
from . import sms_resplit_source_check as source_check

MAX_CHECKS = 32
SECONDS = 30


def names_for(old, candidates, kept):
    """Choose names once, before judging, so checks and insertion see the same namespace."""
    existing = {row['rom_offset']: row for row in old}
    names = {row['rom_offset']: row['name'] for row in old if row['id'] in kept}
    used = set(names.values())
    for fn in candidates:
        if fn.rom in names:
            continue
        row = existing.get(fn.rom)
        name = row['name'] if row and (row['status'] in ('matched', 'documented') or not AUTO_NAME.match(row['name'])) else fn.name
        if name in used:
            name = f'{fn.name}_{fn.rom:06x}' if fn.name in used else fn.name
        names[fn.rom] = name
        used.add(name)
    return names


def affected(before, candidates, regions, *, force=False):
    old = before['tables']['functions']
    def signature(offset, cpu, code, asm, refs, edges):
        return offset, cpu, code, asm, json.dumps(refs or [], sort_keys=True), json.dumps(edges or {}, sort_keys=True)

    layout = {signature(r['rom_offset'], r['vram'], bytes(r['target'] or b''), r['asm'],
                        json.loads(r['relocs'] or '[]'), json.loads(r['meta'] or '{}').get('edges')) for r in old}
    proposed = {signature(f.rom, f.vram, f.code, f.asm, f.refs,
                          {str(k): v for k, v in (getattr(f, 'edges', None) or {}).items()}) for f in candidates}
    data = {(r['rom_offset'], r['size'], r['kind']) for r in before['tables']['data_regions']}
    if not force and layout == proposed and data == {(lo, count, kind) for lo, count, kind, *_ in regions}:
        cfg = json.loads(before['project']['config'])
        return [row for row in old if row['status'] == 'matched' and
                compiler_settings(cfg, row.get('unit')).get('include_dirs')]
    # A changed entry can change a retained caller's symbol binding or instruction/data interpretation too.
    return [r for r in old if r['status'] in ('matched', 'documented')]


def preview(before, candidates, regions, *, force=False):
    rows = affected(before, candidates, regions, force=force)
    return {'source_revalidation_pending': len(rows),
            'source_revalidation_candidates': [{key: row[key] for key in ('id', 'name', 'rom_offset', 'vram', 'status')}
                                                for row in rows[:100]],
            'source_revalidation_candidates_truncated': len(rows) > 100}


def prepare(before, candidates, regions, names, *, force=False):
    results, deadline = {}, time.monotonic() + SECONDS
    by_offset = {fn.rom: fn for fn in candidates}
    for index, row in enumerate(affected(before, candidates, regions, force=force)):
        fn = by_offset.get(row['rom_offset'])
        kind = 'asm' if row['status'] == 'documented' else 'c'
        reason = 'no proposed entry begins at the retained physical offset' if fn is None else None
        if index >= MAX_CHECKS or time.monotonic() >= deadline:
            reason = 'automatic revalidation budget exhausted; retained source needs manual validation'
        result = (source_check.Result('unresolved', kind, (reason,), row['matched_source'] or '') if reason else
                  source_check.check(before, row, fn, names, candidates, regions,
                                     timeout=min(5, max(0.1, (deadline - time.monotonic()) / 2))))
        results[row['id']] = result
    return results


def report(results):
    return {'source_revalidation': {state: sum(r.state == state for r in results.values())
                                    for state in ('passed', 'failed', 'unresolved')},
            'source_revalidation_limits': {'functions': MAX_CHECKS, 'seconds': SECONDS},
            'source_checks': [{'id': fid, **result.report()} for fid, result in list(results.items())[:100]],
            'source_checks_truncated': len(results) > 100}


def apply(db, old, new_ids, kept, results, before_digest, *, checked_plan=None):
    for row in old:
        result = results.get(row['id'])
        fid = row['id'] if row['id'] in kept else new_ids.get(row['rom_offset'])
        if result is None or fid is None:
            continue
        meta = json.loads(row['meta'] or '{}')
        current = json.loads(db.execute('SELECT meta FROM functions WHERE id=?', (fid,)).fetchone()['meta'] or '{}')
        meta.pop('edges', None)
        if 'edges' in current:
            meta['edges'] = current['edges']
        if result.kind == 'asm':
            meta['sample'] = True
        target = db.execute('SELECT target FROM functions WHERE id=?', (fid,)).fetchone()['target']
        meta['resplit_validation'] = {**result.report(), 'semantic_review': 'pending', 'checked_plan': checked_plan,
            'checked_source_sha256': hashlib.sha256(result.source.encode()).hexdigest(),
            'checked_target_sha256': hashlib.sha256(target or b'').hexdigest(),
            'origin': {'snapshot': before_digest, 'function_id': row['id'],
                       'target_sha256': hashlib.sha256(row['target'] or b'').hexdigest()}}
        accepted = result.state == 'passed'
        # Old scores and attempts stay with the original target in history; this records a new mechanical result.
        db.execute('UPDATE functions SET status=?, matched_source=?, matched_agent_id=?, matched_at=?, '
                   'best_source=?,best_score=?,best_agent_id=?,meta=? WHERE id=?',
                   (row['status'] if accepted else ('asm' if result.kind == 'asm' else 'open'),
                    result.source if accepted else None, row['matched_agent_id'] if accepted else None,
                    time.time() if accepted else None, result.source, 0 if accepted else None,
                    row['matched_agent_id'], json.dumps(meta), fid))
