"""The subject-descriptor upgrade preserves pre-existing history, export context and unknown provenance."""
from contextlib import nullcontext
import sqlite3
from threading import RLock
from types import SimpleNamespace

import pytest

from decompnet import store_annotations
from decompnet.store import Store
from decompnet.app import banked_resplit_state as snapshots
from decompnet.app.sms_export_state import stamp
from .test_store_annotations import legacy, original_rows


def previous(path, *, factory=sqlite3.Connection):
    conn, pid = legacy(path, factory=factory)
    for table in store_annotations.TABLES:
        for column in ('annotation', 'evidence'):
            conn.execute(f'ALTER TABLE {table} ADD COLUMN {column} TEXT')
        conn.execute(f'UPDATE {table} SET annotation=?,evidence=?', (' { "version":99,"original":true } ', '{"version":99}'))
    return conn, pid


def test_previous_metadata_migrates_without_inventing_subjects_or_changing_saved_contexts(tmp_path):
    path = tmp_path / 'previous.db'
    conn, pid = previous(path)
    before = original_rows(conn)
    snapshot = snapshots.encode(snapshots.capture(conn, pid, {}))[1]
    net = SimpleNamespace(store=SimpleNamespace(conn=conn, lock=RLock(), tx=lambda: nullcontext(conn)))
    exported = stamp(net, {'id': pid})
    conn.close()
    first = Store(path)
    assert original_rows(first.conn) == before
    assert snapshots.encode(snapshots.capture(first.conn, pid, {}))[1] == snapshot
    net.store = first
    assert stamp(net, {'id': pid}) == exported
    for table in ('notes', 'symbols'):
        assert first.one(f'SELECT subject FROM {table}')['subject'] is None
    assert 'subject' not in {row['name'] for row in first.all('PRAGMA table_info(corrections)')}
    first.conn.close()
    again = Store(path)
    assert original_rows(again.conn) == before
    again.conn.close()


def test_second_subject_alter_failure_rolls_back_both_tables_and_keeps_all_old_metadata(tmp_path):
    class Failing(sqlite3.Connection):
        fail = False
        changes = 0
        def execute(self, sql, *args, **kwargs):
            if self.fail and 'ADD COLUMN subject' in sql:
                self.changes += 1
                if self.changes == 2:
                    raise sqlite3.OperationalError('authored subject migration failure')
            return super().execute(sql, *args, **kwargs)
    conn, _pid = previous(tmp_path / 'rollback.db', factory=Failing)
    before = original_rows(conn)
    conn.fail = True
    with pytest.raises(sqlite3.OperationalError, match='subject migration failure'):
        store_annotations.upgrade(conn)
    assert not conn.in_transaction and original_rows(conn) == before
    for table in ('notes', 'symbols'):
        assert 'subject' not in {row['name'] for row in conn.execute(f'PRAGMA table_info({table})')}
    conn.fail = False
    store_annotations.upgrade(conn)
    assert original_rows(conn) == before
