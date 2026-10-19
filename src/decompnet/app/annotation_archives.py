"""Preserve original research as explicitly inactive private notes before metadata or a subject changes."""
import json
import time

from ..network import NetworkError

PREFIX = 'Archived research v1: '
FIELDS = {'symbol': ('name', 'address', 'size', 'kind'),
          'note': ('id', 'function_id', 'agent_id', 'text', 'created_at')}


def archived(text):
    return isinstance(text, str) and text.startswith(PREFIX)


def is_archive(row):
    return archived(row['text']) and any(row[key] is not None for key in ('annotation', 'evidence', 'subject'))


def save(db, kind, row, reason):
    if row is None or all(row[key] is None for key in ('annotation', 'evidence', 'subject')):
        return None
    if not db.in_transaction:
        raise NetworkError('research archive writes require a transaction')
    text = PREFIX + json.dumps({'state': 'archived_original', 'kind': kind, 'reason': reason,
                                'subject': {key: row[key] for key in FIELDS[kind]}}, ensure_ascii=False, sort_keys=True)
    if len(text.encode()) > 65536:
        raise NetworkError('original subject exceeds the research archive budget; no changes were made')
    return db.execute('INSERT INTO notes(project_id,text,created_at,annotation,evidence,subject) VALUES(?,?,?,?,?,?)',
                      (row['project_id'], text, time.time(), row['annotation'], row['evidence'], row['subject'])).lastrowid
