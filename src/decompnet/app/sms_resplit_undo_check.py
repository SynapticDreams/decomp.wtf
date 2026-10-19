"""Validate accepted work before restoring it; compiler/assembler calls stay outside SQLite writes."""
from __future__ import annotations

import json
from pathlib import Path
import time
from types import SimpleNamespace

from ..network import NetworkError
from ..project import compiler_settings
from ..rom import sms_identity
from . import banked_resplit_state as state, banked_resplit_checks as checks
from . import sms_resplit_source_check as source_check
from .sms_resplit_revalidate import MAX_CHECKS, SECONDS


def _context(snapshot):
    cfg, tables = json.loads(snapshot['project']['config']), snapshot['tables']
    return (cfg.get('rom'), cfg.get('sms_profile'), cfg.get('compiler'), snapshot['inputs'],
            tables['symbols'], tables['data_regions'], tables['context_versions'],
            sorted([(row['name'], row['rom_offset'], row['vram'], row['size'], row['unit'], row['target'])
                    for row in tables['functions']], key=lambda row: row[0]))


def validate(before, current, image):
    context_changed = _context(before) != _context(current)
    live = {row['id']: row for row in current['tables']['functions']}
    fields = ('status', 'matched_source', 'rom_offset', 'vram', 'target', 'unit')
    accepted = [row for row in before['tables']['functions'] if row['status'] in ('matched', 'documented')]
    needed = [row for row in accepted if context_changed or row['id'] not in live or
              any(row[key] != live[row['id']][key] for key in fields)]
    candidates = [SimpleNamespace(rom=row['rom_offset'], vram=row['vram'], code=bytes(row['target'] or b''))
                  for row in before['tables']['functions'] if type(row['rom_offset']) is int and type(row['vram']) is int]
    by_offset = {fn.rom: fn for fn in candidates}
    names = {row['rom_offset']: row['name'] for row in before['tables']['functions'] if row['rom_offset'] in by_offset}
    regions = [(row['rom_offset'], row['size'], row['kind']) for row in before['tables']['data_regions']]
    deadline = time.monotonic() + SECONDS
    for index, row in enumerate(needed):
        fn = by_offset.get(row['rom_offset'])
        if index >= MAX_CHECKS or time.monotonic() >= deadline:
            raise NetworkError('undo source revalidation budget exhausted; use Browse saved work for recovery')
        if fn is None or fn.rom < 0 or image[fn.rom:fn.rom + len(fn.code)] != fn.code:
            raise NetworkError('saved accepted target is not established in the frozen input; history is retained')
        result = source_check.check(before, row, fn, names, candidates, regions,
                                    timeout=min(5, max(0.1, (deadline - time.monotonic()) / 2)))
        if result.state != 'passed':
            raise NetworkError('saved accepted source does not revalidate in the restore context; use Browse saved work for recovery')
    return {'checked': len(needed), 'unchanged': len(accepted) - len(needed)}


def prepare(net, proj, history_id, capture):
    row = net.store.one('SELECT * FROM resplit_history WHERE project_id=? AND id=?', proj['id'], history_id)
    latest = net.store.one('SELECT MAX(id) AS id FROM resplit_history WHERE project_id=? AND undone_at IS NULL', proj['id'])
    if row is None or row['undone_at'] is not None or latest['id'] != history_id:
        raise NetworkError('undo the latest active resplit first')
    before = state.decode(row['before_state'], row['before_digest'])
    cfg = json.loads(before['project']['config'])
    if before['project']['id'] != proj['id']:
        raise NetworkError('resplit snapshot belongs to another project')
    units = [None, *sorted((cfg.get('compiler') or {}).get('units') or {})]
    if 'compiler_dependencies' not in before['inputs'] and any(compiler_settings(cfg, unit).get('include_dirs') for unit in units):
        raise NetworkError('saved resplit has no compiler dependency context; use Browse saved work for recovery')
    current = capture()
    if state.encode(current)[1] != row['after_digest']:
        raise NetworkError('project work or inputs changed after resplit; undo would overwrite newer work')
    path = Path(proj['root']) / cfg['rom']['file']
    checks.verify_input('z80', path, cfg)
    result = validate(before, current, sms_identity.strip_copier_header(path.read_bytes()))
    return before, row['before_digest'], row['after_digest'], result
