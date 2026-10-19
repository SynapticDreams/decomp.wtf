"""Nullable research metadata upgrades; legacy snapshots keep their original digests and unknown provenance."""
from __future__ import annotations

TABLES = ('corrections', 'symbols', 'notes')
OPTIONAL = frozenset(('annotation', 'evidence'))


def upgrade(conn):
    def missing():
        return [(table, column) for table in TABLES
                for column in sorted(OPTIONAL - {row[1] for row in conn.execute(f'PRAGMA table_info({table})')})]
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
    return {key: value for key, value in dict(row).items()
            if table not in TABLES or key not in OPTIONAL or value is not None}


def restore_row(table, row, columns):
    if not isinstance(row, dict):
        return row
    optional = OPTIONAL & columns if table in TABLES else set()
    return {**{key: None for key in optional}, **row}
