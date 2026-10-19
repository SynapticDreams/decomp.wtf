"""Actual SMS/GG work and pending recovery survive metadata schema upgrades; tagged facts remain inactive."""
import sqlite3

import pytest

from decompnet.app.engine import RomNetwork
from decompnet.app import banked_resplit_history as history
from decompnet.store import SCHEMA, MIGRATIONS
from decompnet.rom import gb_build, sms_asm
from decompnet.rom.annotations import dump
from .annotation_fixture import annotation, evidence
from .test_sms_resplit_source_check import project as fixture_project, C, ASM
from .test_sms_profile_migration import function

project = fixture_project
pytestmark = pytest.mark.skipif(not gb_build.available('z80') or not sms_asm.available(), reason='needs pinned GBDK and WLA-DX')


def legacy_copy(source, destination):
    """Copy actual fixture rows into the pre-metadata schema, including pending history blobs."""
    conn = sqlite3.connect(destination, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA.replace('id INTEGER PRIMARY KEY AUTOINCREMENT, project_id INTEGER NOT NULL, name TEXT NOT NULL',
                                    'id INTEGER PRIMARY KEY, project_id INTEGER NOT NULL, name TEXT NOT NULL', 1))
    for table, name, ddl in MIGRATIONS:
        if name not in {row['name'] for row in conn.execute(f'PRAGMA table_info({table})')}:
            conn.execute(f'ALTER TABLE {table} ADD COLUMN {name} {ddl}')
    for table, in conn.execute("SELECT name FROM sqlite_schema WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchall():
        columns = [row['name'] for row in conn.execute(f'PRAGMA table_info({table})')]
        for row in source.execute(f"SELECT {','.join(columns)} FROM {table}"):
            conn.execute(f"INSERT INTO {table} ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})", tuple(row))
    conn.close()


@pytest.mark.parametrize('kind', ['c', 'asm'])
def test_actual_accepted_work_and_old_pending_undo_survive_annotation_migration(project, tmp_path, kind):
    net, slug = project
    agent, _ = net.local_agent('annotation_fixture_writer')
    fn = function(net, slug)
    if kind == 'c':
        source = C
        assert net.attempt(agent, fn['name'], source, slug)['matched']
    else:
        source = ASM.replace('    ret\n', '    ld a, 7\n    ret\n').replace('without changing the caller registers or flags',
            'with the authored result in A and unchanged flags').replace('caller state is preserved', 'A holds seven')
        with net.store.tx() as db:
            db.execute("UPDATE functions SET status='asm' WHERE id=?", (fn['id'],))
        assert net.document_function(agent, slug, fn['name'], source).startswith('✅ DOCUMENTED:')
    with net.store.tx() as db:
        db.execute("INSERT INTO notes(project_id,function_id,text) VALUES(?,?,'authored annotation migration evidence')", (fn['project_id'], fn['id']))
    before = history.capture(net, net.project_row(slug))
    applied = net.resplit_banked(slug, apply=True, log=lambda *_: None)
    after = history.capture(net, net.project_row(slug))
    path = tmp_path / 'old-metadata.db'
    legacy_copy(net.store.conn, path)
    net.store.conn.close()
    upgraded = RomNetwork(path, net.workspace)
    assert history.capture(upgraded, upgraded.project_row(slug)) == after
    upgraded.undo_resplit(slug, applied['history_id'])
    assert history.capture(upgraded, upgraded.project_row(slug)) == before
    restored = function(upgraded, slug)
    assert restored['matched_source'] == source and restored['status'] == ('matched' if kind == 'c' else 'documented')
    assert upgraded.store.one('SELECT annotation,evidence FROM notes')['evidence'] is None


@pytest.mark.parametrize('field', ['annotation', 'evidence'])
@pytest.mark.parametrize('metadata', ['supported', 'future', 'invalid'])
def test_tagged_corrections_cannot_override_actual_accepted_code_before_qualified_consumption(project, field, metadata):
    net, slug = project
    agent, _ = net.local_agent('annotation_guard_writer')
    fn = function(net, slug)
    assert net.attempt(agent, fn['name'], C, slug)['matched']
    value = annotation('data') if field == 'annotation' else evidence()
    if field == 'annotation':
        value['target'].update(offset=fn['rom_offset'], size=fn['size'])
    raw = dump(value) if metadata == 'supported' else '{"version":99,"future_fact":"these bytes are data"}' if metadata == 'future' else '{'
    with net.store.tx() as db:
        db.execute(f'INSERT INTO corrections(project_id,kind,rom_offset,cpu,count,{field}) VALUES(?,?,?,?,?,?)',
                   (fn['project_id'], 'data', fn['rom_offset'], fn['vram'], fn['size'], raw))
    assert not net._hints(net.project_row(slug))['data']
    net.resplit_banked(slug, apply=True, log=lambda *_: None)
    current = function(net, slug)
    assert current['matched_source'] == C and current['status'] == 'matched'
    assert net.store.one(f'SELECT {field} FROM corrections')[field] == raw
