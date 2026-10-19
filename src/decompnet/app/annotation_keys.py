"""Existing note/symbol row identities and receipt fields, without parallel research records."""
from ..network import NetworkError
from . import annotation_receipts as receipts, sms_annotation_context as context

TABLES = {'note': 'notes', 'symbol': 'symbols'}
FIELDS = {'note': ('id', 'project_id', 'function_id', 'agent_id', 'text', 'created_at', 'annotation', 'evidence', 'subject'),
          'symbol': ('project_id', 'name', 'address', 'size', 'kind', 'annotation', 'evidence', 'subject')}


def key(kind, value):
    if kind not in TABLES:
        raise NetworkError('research subject kind is note or symbol')
    if kind == 'note':
        if type(value) is not int or not 0 < value < 2**63:
            raise NetworkError('note ID must be a positive integer')
    elif not isinstance(value, str) or not value or len(value) > 256 or '\0' in value:
        raise NetworkError('symbol name is unavailable or exceeds its budget')
    return value


def fetch(net, proj, kind, value):
    value = key(kind, value)
    column = 'id' if kind == 'note' else 'name'
    row = net.store.one(f'SELECT * FROM {TABLES[kind]} WHERE project_id=? AND {column}=?', proj['id'], value)
    if row is None:
        raise NetworkError(f'no such {kind}')
    return row


def receipt_key(kind, row):
    return context.digest({'kind': kind, 'key': row['id'] if kind == 'note' else row['name']})


def trusted(net, kind, row):
    try:
        return receipts.trusted(net, row, FIELDS[kind], kind='annotation_review', key=receipt_key(kind, row))
    except (TypeError, ValueError, OverflowError):
        return False


def record(net, db, kind, row):
    receipts.record(net, db, row, FIELDS[kind], kind='annotation_review', key=receipt_key(kind, row))
