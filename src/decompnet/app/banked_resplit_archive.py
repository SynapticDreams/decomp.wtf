"""Bounded, operator-facing forward recovery from SMS/GG resplit snapshots."""
from __future__ import annotations

import json
import re

from ..network import NetworkError
from . import banked_resplit_state as state
from .sms_resplit_dependencies import MAX_FILES
from .banked_resplit_archive_items import function_info, items, metadata
from . import banked_resplit_project_archive as project_archive, banked_resplit_archive_text as archive_text

PAGE = 25
MAX_CHARS = 262_144
CHARS = 16_384  # Default: at most 64 KiB UTF-8; larger requested chunks are capped at 1 MiB.


def integer(value, name, *, minimum=0, maximum=2**63 - 1):
    if type(value) is int:
        number = value
    elif isinstance(value, str) and re.fullmatch(r'[0-9]{1,19}', value):
        number = int(value)
    else:
        raise NetworkError(f'{name} must be an integer')
    if not minimum <= number <= maximum:
        raise NetworkError(f'{name} is outside the supported range')
    return number


def _page(rows, offset):
    if offset > len(rows):
        raise NetworkError('archive page is outside the saved records')
    end = offset + PAGE
    return {'total': len(rows), 'next_offset': end if end < len(rows) else None, 'limit': PAGE}, rows[offset:end]


def read(net, slug, history_id, *, function_id=None, item=None, offset=0, start=0, limit=CHARS, scope='function'):
    """Explicit inspection only: never restore rows, accept source, release claims or verify against current work."""
    proj = net._project(slug)
    if net.cfg(proj).get('arch') != 'z80' or slug in net.links or net.fork_slug(slug):
        raise NetworkError('resplit archive recovery is for local SMS/GG projects')
    history_id = integer(history_id, 'history ID', minimum=1)
    offset = integer(offset, 'archive offset', maximum=state.MAX_ROWS + MAX_FILES + 10)
    start = integer(start, 'text start', maximum=state.MAX_BYTES)
    limit = integer(limit, 'text chunk limit', minimum=1, maximum=MAX_CHARS)
    if scope not in ('function', 'project') or (scope == 'project' and function_id is not None):
        raise NetworkError('select either project context or a saved function')
    pattern = (r'(project|compiler|symbols|claims|dependencies|(?:note|header|correction|data):[0-9]{1,19})' if scope == 'project' else
               r'(accepted|best|compiler|symbols|review|provenance|dependencies|(?:attempt|note|header|dependency):[0-9]{1,19})')
    if item is not None and (not isinstance(item, str) or not re.fullmatch(pattern, item)):
        raise NetworkError('unknown archive item selector')
    if scope == 'function' and function_id is None and (item is not None or start):
        raise NetworkError('select a saved function before requesting text')
    if item is None and start:
        raise NetworkError('select a saved item before requesting text')
    saved = net.store.one('SELECT before_state,before_digest,created_at,undone_at FROM resplit_history '
                          'WHERE project_id=? AND id=?', proj['id'], history_id)
    if saved is None:
        raise NetworkError('saved resplit is unavailable in this project')
    snapshot = state.decode(saved['before_state'], saved['before_digest'])
    try:
        return _read(snapshot, saved, proj['id'], history_id, function_id, item, offset, start, limit, scope)
    except (KeyError, TypeError, ValueError, AttributeError):
        raise NetworkError('saved resplit records are malformed') from None


def _read(snapshot, saved, pid, history_id, function_id, item, offset, start, limit, scope):
    if snapshot['project']['id'] != pid:
        raise NetworkError('saved resplit belongs to a different project')
    tables = snapshot['tables']
    if any(not isinstance(rows, list) for rows in tables.values()) or 1 + sum(map(len, tables.values())) > state.MAX_ROWS:
        raise NetworkError('saved resplit exceeds the supported row budget')
    cfg = json.loads(snapshot['project']['config'])
    rom = cfg.get('rom', {})
    identity = rom.get('identity') or {}
    profile = cfg.get('sms_profile') or {}
    origin = metadata({'history_id': history_id, 'snapshot_sha256': saved['before_digest'], 'created_at': saved['created_at'],
              'undone_at': saved['undone_at'], 'platform': cfg.get('platform'), 'sha1': rom.get('sha1'),
              'product_code': identity.get('product_code'), 'revision': identity.get('revision'),
              'mapper': profile.get('mapper'), 'intent': profile.get('variant')})
    origin['normalized'] = metadata({key: (identity.get('normalized') or {}).get(key) for key in ('sha256', 'size')})
    if any(row['project_id'] != pid for row in tables['functions']):
        raise NetworkError('saved function belongs to a different project')
    if scope == 'project':
        options = project_archive.items(snapshot)
        subject = {'project_context': {'name': 'Saved project context', 'scope': 'project'}}
        if item is None:
            page, options = _page(options, offset)
            return {'origin': origin, **subject, **page, 'items': [entry.summary() for entry in options]}
        return archive_text.read(options, item, origin, subject, f'project_{pid}', start, limit)
    if function_id is None:
        rows = sorted(tables['functions'], key=lambda r: r['id'])
        page, rows = _page(rows, offset)
        return {'origin': origin, **page, 'functions': [function_info(row) for row in rows], 'project_context_available': True}
    fid = integer(function_id, 'function ID', minimum=1)
    row = next((row for row in tables['functions'] if row['id'] == fid), None)
    if row is None:
        raise NetworkError('saved function is unavailable in this resplit')
    options = items(snapshot, row)
    if item is None:
        page, options = _page(options, offset)
        return {'origin': origin, 'function': function_info(row), **page, 'items': [entry.summary() for entry in options]}
    return archive_text.read(options, item, origin, {'function': function_info(row)}, f'function_{fid}', start, limit)


def query(net, slug, params):
    """Keep query parsing out of the shared server's route body."""
    return read(net, slug, params.get('history'), function_id=params.get('function'), item=params.get('item'),
                offset=params.get('offset', 0), start=params.get('start', 0), limit=params.get('limit', CHARS),
                scope=params.get('scope', 'function'))
