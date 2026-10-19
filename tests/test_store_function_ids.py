"""Automatic IDs never attach deleted work to a later import; old databases migrate atomically."""
import sqlite3

import pytest

from decompnet.store import MIGRATIONS, SCHEMA, Store


def project(conn):
    return conn.execute("INSERT INTO projects(slug,root,config) VALUES('fixture','project','{}')").lastrowid


def function(conn, pid, name='Entry'):
    return conn.execute('INSERT INTO functions(project_id,name,target) VALUES(?,?,?)', (pid, name, b'\xc9')).lastrowid


def legacy(path):
    conn = sqlite3.connect(path, isolation_level=None)
    conn.row_factory = sqlite3.Row
    schema = SCHEMA.replace('id INTEGER PRIMARY KEY AUTOINCREMENT, project_id INTEGER NOT NULL, name TEXT NOT NULL',
                            'id INTEGER PRIMARY KEY, project_id INTEGER NOT NULL, name TEXT NOT NULL', 1)
    conn.executescript(schema)
    for table, name, ddl in MIGRATIONS:
        if name not in {row['name'] for row in conn.execute(f'PRAGMA table_info({table})')}:
            conn.execute(f'ALTER TABLE {table} ADD COLUMN {name} {ddl}')
    conn.execute("INSERT INTO settings VALUES('abandons_recounted','1')")
    pid = project(conn)
    fid = function(conn, pid, 'Retained')
    conn.execute("UPDATE functions SET meta=?,matched_source=?,best_source=?,status='documented' WHERE id=?",
                 ('{"sample":true}', 'fixture accepted source', 'fixture best source', fid))
    return conn, pid, fid


def test_deleted_ids_are_not_reused_even_after_all_functions_are_removed_and_reopened(tmp_path):
    path = tmp_path / 'state.db'
    store = Store(path)
    pid = project(store.conn)
    old_id = function(store.conn, pid)
    store.conn.execute("INSERT INTO attempts(function_id,source) VALUES(?,'Retained old attempt')", (old_id,))
    store.conn.execute('DELETE FROM functions WHERE id=?', (old_id,))
    fresh = function(store.conn, pid, 'LaterImport')
    assert fresh > old_id and not store.conn.execute('SELECT 1 FROM attempts WHERE function_id=?', (fresh,)).fetchone()
    store.conn.execute('DELETE FROM functions')
    store.conn.close()
    store = Store(path)
    assert function(store.conn, pid, 'AfterRestart') > fresh
    store.conn.close()


def test_upgrade_preserves_every_function_field_indexes_views_triggers_and_foreign_keys(tmp_path):
    path = tmp_path / 'old.db'
    conn, pid, fid = legacy(path)
    conn.execute('ALTER TABLE functions ADD COLUMN custom_tag TEXT')
    conn.execute("UPDATE functions SET custom_tag='retained extension' WHERE id=?", (fid,))
    conn.executescript('''
        PRAGMA foreign_keys=ON;
        CREATE TABLE linked(function_id INTEGER REFERENCES functions(id) ON DELETE CASCADE);
        CREATE TABLE audit(value TEXT);
        CREATE INDEX custom_function_index ON functions(custom_tag);
        CREATE VIEW function_names AS SELECT id,name FROM functions;
        CREATE VIEW dependent_names AS SELECT name FROM function_names;
        CREATE TRIGGER function_audit AFTER UPDATE OF name ON functions BEGIN INSERT INTO audit VALUES(NEW.name); END;
        CREATE TRIGGER note_audit AFTER INSERT ON notes BEGIN
            INSERT INTO audit SELECT name FROM functions WHERE id=NEW.function_id;
        END;
    ''')
    conn.execute('INSERT INTO linked VALUES(?)', (fid,))
    before = dict(conn.execute('SELECT * FROM functions WHERE id=?', (fid,)).fetchone())
    indexes = {row['name'] for row in conn.execute("SELECT name FROM sqlite_schema WHERE type='index' AND tbl_name='functions'")}
    conn.close()
    schema_version = None
    for _ in range(2):
        store = Store(path)
        conn = store.conn
        assert dict(conn.execute('SELECT * FROM functions WHERE id=?', (fid,)).fetchone()) == before
        assert {row['name'] for row in conn.execute("SELECT name FROM sqlite_schema WHERE type='index' AND tbl_name='functions'")} >= indexes
        assert conn.execute('SELECT function_id FROM linked').fetchone()[0] == fid
        assert conn.execute('SELECT name FROM dependent_names').fetchone()[0] == 'Retained'
        assert conn.execute('PRAGMA foreign_keys').fetchone()[0] == 1
        assert not conn.execute('PRAGMA foreign_key_check').fetchall()
        current = conn.execute('PRAGMA schema_version').fetchone()[0]
        assert schema_version is None or current == schema_version
        schema_version = current
        conn.close()
    store = Store(path)
    store.conn.execute("UPDATE functions SET name='Updated' WHERE id=?", (fid,))
    store.conn.execute("INSERT INTO notes(project_id,function_id,text) VALUES(?,?,'new note')", (pid, fid))
    assert [row[0] for row in store.conn.execute('SELECT value FROM audit')] == ['Updated', 'Updated']
    store.conn.close()


@pytest.mark.parametrize('related', ['attempts', 'claims', 'notes', 'twin_misses'])
@pytest.mark.parametrize('empty', [False, True])
def test_upgrade_seeds_beyond_legacy_orphan_references_without_reattributing_them(tmp_path, related, empty):
    path = tmp_path / 'old.db'
    conn, pid, _fid = legacy(path)
    query = {
        'attempts': "INSERT INTO attempts(function_id,source) VALUES(256,'Unknown former target')",
        'claims': 'INSERT INTO claims(function_id,agent_id) VALUES(256,1)',
        'notes': "INSERT INTO notes(function_id,text) VALUES(256,'Unknown former target')",
        'twin_misses': "INSERT INTO twin_misses(function_id,source_hash) VALUES(256,'fixture')",
    }[related]
    conn.execute(query)
    if empty:
        conn.execute('DELETE FROM functions')
    before = [dict(row) for row in conn.execute(f'SELECT * FROM {related}')]
    conn.close()
    store = Store(path)
    fresh = function(store.conn, pid, 'AfterUpgrade')
    assert fresh > 256 and [dict(row) for row in store.conn.execute(f'SELECT * FROM {related}')] == before
    assert not store.conn.execute(f'SELECT 1 FROM {related} WHERE function_id=?', (fresh,)).fetchone()
    store.conn.close()


def test_existing_allocator_also_advances_past_unowned_references_on_reopen(tmp_path):
    path = tmp_path / 'state.db'
    store = Store(path)
    pid = project(store.conn)
    function(store.conn, pid)
    store.conn.execute("INSERT INTO attempts(function_id,source) VALUES(256,'Unowned reference')")
    store.conn.close()
    store = Store(path)
    assert function(store.conn, pid, 'AfterReopen') > 256
    store.conn.close()


@pytest.mark.parametrize('fail_at', ['rename', 'commit'])
def test_failed_upgrade_restores_original_table_objects_and_foreign_key_enforcement(tmp_path, fail_at):
    from decompnet.store_ids import upgrade
    path = tmp_path / 'old.db'
    conn, _pid, _fid = legacy(path)
    conn.executescript('PRAGMA foreign_keys=ON; CREATE VIEW names AS SELECT name FROM functions;')
    before = [tuple(row) for row in conn.execute("SELECT type,name,sql FROM sqlite_schema ORDER BY name")]
    functions = [dict(row) for row in conn.execute('SELECT * FROM functions')]

    def authorize(action, arg1, _arg2, _database, _trigger):
        if (fail_at == 'rename' and action == sqlite3.SQLITE_ALTER_TABLE) or \
                (fail_at == 'commit' and action == sqlite3.SQLITE_TRANSACTION and arg1 == 'COMMIT'):
            return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK

    conn.set_authorizer(authorize)
    with pytest.raises(sqlite3.DatabaseError):
        upgrade(conn)
    conn.set_authorizer(None)
    assert not conn.in_transaction and conn.execute('PRAGMA foreign_keys').fetchone()[0] == 1
    assert [tuple(row) for row in conn.execute("SELECT type,name,sql FROM sqlite_schema ORDER BY name")] == before
    assert [dict(row) for row in conn.execute('SELECT * FROM functions')] == functions
    upgrade(conn)
    assert 'AUTOINCREMENT' in conn.execute("SELECT sql FROM sqlite_schema WHERE name='functions'").fetchone()[0]
    conn.close()
