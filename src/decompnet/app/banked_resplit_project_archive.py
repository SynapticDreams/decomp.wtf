"""Explicit project-owned recovery records, independent of saved function availability."""
import json

from ..network import NetworkError
from .banked_resplit_archive_items import Item
from .banked_resplit_state import _blob


def encoded(value):
    return json.dumps(value, default=_blob, sort_keys=True, separators=(',', ':'))


def items(snapshot):
    tables, pid = snapshot['tables'], snapshot['project']['id']
    owned = ('notes', 'symbols', 'data_regions', 'corrections', 'context_versions')
    if any(row['project_id'] != pid for table in owned for row in tables[table]):
        raise NetworkError('saved project record belongs to another project')
    functions = {row['id'] for row in tables['functions']}
    if any(row['function_id'] not in functions for table in ('attempts', 'claims') for row in tables[table]):
        raise NetworkError('saved related record has no established project ownership')
    cfg = json.loads(snapshot['project']['config'])
    manifest = {'version': 1, 'platform': cfg.get('platform'), 'rom': cfg.get('rom'), 'sms_profile': cfg.get('sms_profile'),
                'counts': {table: len(tables[table]) for table in (*owned, 'functions', 'attempts', 'claims')},
                'scope': 'saved project reference; does not restore or accept work'}
    out = [Item('project', 'Saved project manifest', lambda: encoded(manifest), {}, 'json'),
           Item('compiler', 'Saved project and unit compiler settings', lambda: encoded(cfg.get('compiler')), {}, 'json'),
           Item('symbols', 'Saved symbol context', lambda: encoded(tables['symbols']), {}, 'json'),
           Item('claims', 'Saved claims (reference only)', lambda: encoded(tables['claims']), {}, 'json')]
    if 'compiler_dependencies' in snapshot['inputs']:
        bundle = {'encoding': 'binary content uses base64 in $blob objects',
                  'capture_point': 'resplit snapshot; prior acceptance context is not established by capture',
                  'bundle': snapshot['inputs']['compiler_dependencies']}
        out.append(Item('dependencies', 'Saved compiler dependency bundle', lambda: encoded(bundle), {}, 'json'))
    for row in sorted(tables['notes'], key=lambda row: row['id']):
        fid = row['function_id']
        provenance = {key: row.get(key) for key in ('id', 'agent_id', 'created_at', 'function_id')}
        provenance['text_was_null'] = row['text'] is None
        provenance['association'] = 'project' if fid is None else 'saved-function' if fid in functions else 'unknown-former-function'
        out.append(Item(f"note:{row['id']}", f"Saved note {row['id']}", row['text'] or '', provenance))
    for row in sorted(tables['context_versions'], key=lambda row: row['version']):
        provenance = {key: row.get(key) for key in ('version', 'unit', 'agent_id', 'created_at')}
        out.append(Item(f"header:{row['version']}", f"Saved header {row['version']} ({row['unit'] or 'project'})",
                        row['header'] or '', provenance, 'h'))
    for table, prefix, key in (('corrections', 'correction', 'id'), ('data_regions', 'data', 'rom_offset')):
        for row in sorted(tables[table], key=lambda row: row[key]):
            out.append(Item(f'{prefix}:{row[key]}', f'Saved {prefix} {row[key]}', lambda row=row: encoded(row), {}, 'json'))
    return out
