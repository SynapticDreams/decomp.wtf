"""Actual accepted C/assembly survives old-schema migration, profile resplit and guarded undo."""
import re
import sqlite3

import pytest

from decompnet.app.engine import RomNetwork
from decompnet.rom import gb_build, sms_asm

from .test_sms_profile_migration import project as fixture_project, proposal, snapshot, function
from .test_sms_resplit_source_check import C, ASM

project = fixture_project


@pytest.mark.skipif(not gb_build.available('z80') or not sms_asm.available(), reason='needs pinned GBDK and WLA-DX')
@pytest.mark.parametrize('kind', ['c', 'asm'])
def test_old_schema_source_is_migrated_revalidated_and_restored_without_losing_work(project, tmp_path, kind):
    net, slug = project
    agent, _ = net.local_agent('legacy_fixture_writer')
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
        db.execute('INSERT INTO notes(project_id,function_id,text) VALUES(?,?,?)',
                   (fn['project_id'], fn['id'], 'Authored evidence retained across old database migration.'))
        db.execute('DROP TABLE resplit_history')
    before = snapshot(net, slug)
    dump = '\n'.join(line for line in net.store.conn.iterdump() if 'sqlite_sequence' not in line)
    dump, replacements = re.subn(r'(id INTEGER PRIMARY KEY) AUTOINCREMENT', r'\1', dump, count=1)
    assert replacements == 1
    net.store.conn.close()
    old_path = tmp_path / 'legacy.db'
    with sqlite3.connect(old_path) as old:
        old.executescript(dump)
        assert 'AUTOINCREMENT' not in old.execute("SELECT sql FROM sqlite_schema WHERE name='functions'").fetchone()[0]
        assert old.execute("SELECT 1 FROM sqlite_schema WHERE name='resplit_history'").fetchone() is None
    upgraded = RomNetwork(old_path, tmp_path / 'projects')
    upgraded.auto_install_tools = False
    upgraded.on_match = lambda *_: None
    assert snapshot(upgraded, slug) == before
    assert 'AUTOINCREMENT' in upgraded.store.one("SELECT sql FROM sqlite_schema WHERE name='functions'")['sql']
    assert not upgraded.resplit_history(slug)['history']
    requested = proposal()
    preview = upgraded.resplit_banked(slug, profile=requested, log=lambda *_: None)
    applied = upgraded.resplit_banked(slug, profile=requested, expected_plan=preview['plan'], apply=True, log=lambda *_: None)
    current = function(upgraded, slug)
    assert applied['source_revalidation']['passed'] == 1
    assert current['id'] == fn['id'] and current['matched_source'] == source
    assert current['status'] == ('matched' if kind == 'c' else 'documented')
    upgraded.undo_resplit(slug, applied['history_id'])
    assert snapshot(upgraded, slug) == before
    assert not upgraded.store.conn.execute('PRAGMA foreign_key_check').fetchall()
