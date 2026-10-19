"""Operator review authority is an application event, never a caller's JSON claim."""
from . import annotation_receipts as receipts

FIELDS = ('id', 'project_id', 'kind', 'rom_offset', 'cpu', 'count', 'reason', 'agent_id',
          'created_at', 'annotation', 'evidence')


def digest(row):
    return receipts.digest(row, FIELDS)


def trusted(net, row):
    return receipts.trusted(net, row, FIELDS, kind='correction_review', key=str(row['id']))


def record(net, db, row):
    receipts.record(net, db, row, FIELDS, kind='correction_review', key=str(row['id']))
