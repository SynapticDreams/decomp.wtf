"""Selected text and provenance from a private resplit snapshot; no live-project mutation."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Callable

from ..project import compiler_settings


@dataclass
class Item:
    key: str
    label: str
    text: str | Callable[[], str]
    provenance: dict
    extension: str = 'txt'

    def summary(self):
        return {'key': self.key, 'label': self.label[:512], 'provenance': metadata(self.provenance),
                'label_truncated': len(self.label) > 512,
                'characters': len(self.text) if isinstance(self.text, str) else None}

    def body(self):
        return self.text() if callable(self.text) else self.text


def metadata(values):
    if any(value is not None and not isinstance(value, (str, int, float, bool)) for value in values.values()):
        raise TypeError('metadata must contain scalar values')
    clipped = [key for key, value in values.items() if isinstance(value, str) and len(value) > 512]
    return {**{key: value[:512] if isinstance(value, str) else value for key, value in values.items()},
            'fields_truncated': clipped}


def function_info(row):
    return {**metadata({key: row[key] for key in ('id', 'name', 'rom_offset', 'vram', 'size', 'status', 'unit')}),
            'target_sha256': hashlib.sha256(row['target'] or b'').hexdigest(),
            'has_source': bool(row['matched_source'] or row['best_source'])}


def full_provenance(snapshot, row):
    tables, pid, fid = snapshot['tables'], row['project_id'], row['id']
    omit = lambda value, keys: {key: item for key, item in value.items() if key not in keys}
    return {'function': {**omit(row, ('target', 'asm', 'matched_source', 'best_source')),
                         'target_sha256': hashlib.sha256(row['target'] or b'').hexdigest()},
            'attempts': [omit(value, ('source',)) for value in tables['attempts'] if value['function_id'] == fid],
            'notes': [omit(value, ('text',)) for value in tables['notes'] if value['project_id'] == pid and value['function_id'] == fid],
            'headers': [omit(value, ('header',)) for value in tables['context_versions']
                        if value['project_id'] == pid and value['unit'] in ('', row['unit'])]}


def items(snapshot, row):
    tables, out = snapshot['tables'], []
    extension = 'asm' if row['status'] == 'documented' else 'c' if row['status'] == 'matched' else 'txt'
    for key, label, field, agent in (('accepted', 'Previously accepted source', 'matched_source', 'matched_agent_id'),
                                     ('best', 'Saved best source', 'best_source', 'best_agent_id')):
        if row[field] is not None:
            out.append(Item(key, label, row[field], {'agent_id': row[agent], 'status': row['status'],
                                                    'accepted_at': row['matched_at'] if key == 'accepted' else None}, extension))
    for attempt in sorted(tables['attempts'], key=lambda r: r['id']):
        if attempt['function_id'] == row['id'] and attempt['source'] is not None:
            provenance = {key: attempt.get(key) for key in ('id', 'agent_id', 'score', 'compiled', 'context_version',
                                                          'created_at', 'via', 'kind', 'model', 'effort', 'stage', 'method')}
            out.append(Item(f"attempt:{attempt['id']}", f"Attempt {attempt['id']} (score {attempt['score']})",
                            attempt['source'], provenance, 'asm' if attempt.get('via') == 'asm' else 'c'))
    for note in sorted(tables['notes'], key=lambda r: r['id']):
        if note['project_id'] == row['project_id'] and note['function_id'] == row['id']:
            out.append(Item(f"note:{note['id']}", f"Note {note['id']}", note['text'],
                            {key: note.get(key) for key in ('id', 'agent_id', 'created_at')}))
    for context in sorted(tables['context_versions'], key=lambda r: r['version']):
        if context['project_id'] == row['project_id'] and context['unit'] in ('', row['unit']):
            out.append(Item(f"header:{context['version']}", f"Header {context['version']} ({context['unit'] or 'project'})",
                            context['header'] or '', {key: context.get(key) for key in ('version', 'unit', 'agent_id', 'created_at')}, 'h'))
    cfg = json.loads(snapshot['project']['config'])
    out.extend((Item('provenance', 'Full saved provenance', lambda: json.dumps(full_provenance(snapshot, row),
                                                                            sort_keys=True, separators=(',', ':')), {}, 'json'),
                Item('compiler', 'Saved compiler settings', lambda: json.dumps(compiler_settings(cfg, row['unit']),
                                                                              sort_keys=True, separators=(',', ':')), {}, 'json'),
                Item('symbols', 'Saved symbol context', lambda: json.dumps(tables['symbols'], sort_keys=True, separators=(',', ':')), {}, 'json'),
                Item('review', 'Saved review metadata', row['meta'] or '{}', {}, 'json')))
    return out
