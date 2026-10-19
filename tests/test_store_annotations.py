"""Metadata upgrades preserve old work, unknown fields and legacy snapshot identities."""
import sqlite3
from contextlib import nullcontext
from threading import RLock
from types import SimpleNamespace

import pytest

from decompnet.store import SCHEMA, MIGRATIONS, Store
from decompnet import store_annotations
from decompnet.app import banked_resplit_state as snapshots
from decompnet.app.banked_resplit_restore import restore
from decompnet.app.sms_export_state import stamp
from decompnet.network import NetworkError
from decompnet.rom.annotations import dump
from .annotation_fixture import annotation, evidence


def legacy(path, *, factory=sqlite3.Connection):
    conn = sqlite3.connect(path, isolation_level=None, factory=factory)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    for table, name, ddl in MIGRATIONS:
        if name not in {row['name'] for row in conn.execute(f'PRAGMA table_info({table})')}:
            conn.execute(f'ALTER TABLE {table} ADD COLUMN {name} {ddl}')
    pid = conn.execute("INSERT INTO projects(slug,root,config) VALUES('authored','project','{}')").lastrowid
    conn.execute("INSERT INTO notes(project_id,text,created_at) VALUES(?,'original note',1)", (pid,))
    conn.execute("INSERT INTO symbols(project_id,name,address) VALUES(?,'OriginalSymbol',512)", (pid,))
    conn.execute("INSERT INTO corrections(project_id,kind,rom_offset,cpu,count,reason) VALUES(?,'data',768,768,3,'original reason')", (pid,))
    return conn, pid


def original_rows(conn):
    return {table: [store_annotations.snapshot_row(table, row) for row in conn.execute(f'SELECT * FROM {table}')]
            for table in store_annotations.TABLES}


def test_upgrade_is_idempotent_and_leaves_original_records_unknown(tmp_path):
    path = tmp_path / 'legacy.db'
    conn, _pid = legacy(path)
    before = original_rows(conn)
    conn.close()
    first = Store(path)
    assert original_rows(first.conn) == before
    for table in store_annotations.TABLES:
        assert all(row['annotation'] is None and row['evidence'] is None for row in first.conn.execute(f'SELECT * FROM {table}'))
    first.conn.close()
    second = Store(path)
    assert original_rows(second.conn) == before
    second.conn.close()


def test_metadata_migration_rolls_back_all_columns_if_one_alter_fails(tmp_path):
    class Failing(sqlite3.Connection):
        fail = False
        alterations = 0
        def execute(self, sql, *args, **kwargs):
            if self.fail and sql.startswith('ALTER TABLE'):
                self.alterations += 1
                if self.alterations == 2:
                    raise sqlite3.OperationalError('authored migration failure')
            return super().execute(sql, *args, **kwargs)
    conn, _pid = legacy(tmp_path / 'failed.db', factory=Failing)
    before = original_rows(conn)
    conn.fail = True
    with pytest.raises(sqlite3.OperationalError, match='authored migration'):
        store_annotations.upgrade(conn)
    assert not conn.in_transaction and original_rows(conn) == before
    for table in store_annotations.TABLES:
        assert not store_annotations.OPTIONAL & {row['name'] for row in conn.execute(f'PRAGMA table_info({table})')}
    conn.fail = False
    store_annotations.upgrade(conn)
    assert original_rows(conn) == before


def test_old_snapshot_digest_survives_nullable_schema_upgrade_and_restore(tmp_path):
    path = tmp_path / 'snapshot.db'
    conn, pid = legacy(path)
    original = snapshots.capture(conn, pid, {})
    payload, digest = snapshots.encode(original)
    conn.close()
    store = Store(path)
    assert snapshots.encode(snapshots.capture(store.conn, pid, {}))[1] == digest
    state = snapshots.decode(payload, digest)
    with store.tx() as db:
        db.execute("UPDATE notes SET text='changed after snapshot' WHERE project_id=?", (pid,))
        restore(db, pid, state)
    assert snapshots.encode(snapshots.capture(store.conn, pid, {}))[1] == digest
    assert store.one('SELECT annotation,evidence FROM notes')['evidence'] is None


def test_export_context_survives_nullable_upgrade_and_detects_new_metadata(tmp_path):
    path = tmp_path / 'export-context.db'
    conn, pid = legacy(path)
    net = SimpleNamespace(store=SimpleNamespace(conn=conn, lock=RLock(), tx=lambda: nullcontext(conn)))
    before = stamp(net, {'id': pid})
    conn.close()
    net.store = Store(path)
    assert stamp(net, {'id': pid}) == before
    net.store.conn.execute('UPDATE notes SET evidence=? WHERE project_id=?', (dump(evidence()), pid))
    assert stamp(net, {'id': pid}) != before
    net.store.conn.execute('UPDATE notes SET evidence=NULL WHERE project_id=?', (pid,))
    assert stamp(net, {'id': pid}) == before


@pytest.mark.parametrize('supported', [False, True])
def test_supported_and_future_metadata_are_preserved_byte_for_byte_across_reload_and_restore(tmp_path, supported):
    path = tmp_path / 'metadata.db'
    store = Store(path)
    pid = store.conn.execute("INSERT INTO projects(slug,root,config) VALUES('authored','project','{}')").lastrowid
    future = ' { "version": 99, "future": [true, "original spelling"] } '
    raw, provenance = (dump(annotation()), dump(evidence())) if supported else (future, future)
    for table, sql in (
        ('notes', 'INSERT INTO notes(project_id,text,annotation,evidence) VALUES(?,?,?,?)'),
        ('symbols', 'INSERT INTO symbols(project_id,name,annotation,evidence,address) VALUES(?,?,?,?,512)'),
        ('corrections', "INSERT INTO corrections(project_id,kind,annotation,evidence,rom_offset) VALUES(?,?,?,?,768)")):
        store.conn.execute(sql, (pid, 'data' if table == 'corrections' else 'Authored', raw, provenance))
    before = snapshots.capture(store.conn, pid, {})
    payload, digest = snapshots.encode(before)
    store.conn.close()
    reloaded = Store(path)
    assert snapshots.capture(reloaded.conn, pid, {}) == before
    with reloaded.tx() as db:
        db.execute('UPDATE notes SET evidence=NULL WHERE project_id=?', (pid,))
        restore(db, pid, snapshots.decode(payload, digest))
    for table in store_annotations.TABLES:
        row = reloaded.one(f'SELECT annotation,evidence FROM {table}')
        assert row['annotation'] == raw and row['evidence'] == provenance


def test_restore_still_refuses_missing_required_or_unknown_future_columns(tmp_path):
    conn, pid = legacy(tmp_path / 'strict.db')
    state = snapshots.capture(conn, pid, {})
    store_annotations.upgrade(conn)
    state['tables']['notes'][0].pop('text')
    with pytest.raises(NetworkError, match='schema differs'):
        restore(conn, pid, state)
    state['tables']['notes'][0]['text'] = 'original note'
    state['tables']['notes'][0]['unknown_future_column'] = 'uninterpreted'
    with pytest.raises(NetworkError, match='schema differs'):
        restore(conn, pid, state)
