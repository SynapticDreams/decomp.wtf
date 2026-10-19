"""Nullable research metadata upgrades; legacy snapshots keep their original digests and unknown provenance."""
from __future__ import annotations

TABLES = ('corrections', 'symbols', 'notes')
OPTIONAL = frozenset(('annotation', 'evidence'))


def optional(table):
    if table not in TABLES:
        return frozenset()
    return OPTIONAL | {'subject'} if table in ('notes', 'symbols') else OPTIONAL


def upgrade(conn):
    def missing():
        return [(table, column) for table in TABLES
                for column in sorted(optional(table) - {row[1] for row in conn.execute(f'PRAGMA table_info({table})')})]
    if not missing():
        return
    if conn.in_transaction:
        raise ValueError('annotation metadata migration requires an idle connection')
    conn.execute('BEGIN IMMEDIATE')
    try:
        for table, column in missing():
            conn.execute(f'ALTER TABLE {table} ADD COLUMN {column} TEXT')
        conn.execute('COMMIT')
    except BaseException:
        if conn.in_transaction:
            conn.execute('ROLLBACK')
        raise


def snapshot_row(table, row):
    """Omit only newly optional NULL fields, preserving the pre-upgrade snapshot representation."""
    columns = optional(table)
    return {key: value for key, value in dict(row).items()
            if key not in columns or value is not None}


def restore_row(table, row, columns):
    if not isinstance(row, dict):
        return row
    return {**{key: None for key in optional(table) & columns}, **row}
