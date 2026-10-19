"""Real symbol lifecycle operations retain original research and accepted C/assembly work."""
import pytest

from decompnet.app import annotation_archives as archives, banked_resplit_history as history, symbol_records
from decompnet.network import NetworkError
from decompnet.rom import gb_build, sms_asm
from .annotation_fixture import annotation
from .test_sms_annotation_subjects import project as fixture_project, put, review, symbol
from .test_sms_resplit_source_check import C, ASM
from .test_sms_profile_migration import function

project = fixture_project
TOOLS = pytest.mark.skipif(not gb_build.available('z80') or not sms_asm.available(), reason='needs pinned GBDK and WLA-DX')


def accepted(net, slug, agent, kind):
    fn = function(net, slug)
    if kind == 'c':
        assert net.attempt(agent, fn['name'], C, slug)['matched']
        return C
    source = ASM.replace('    ret\n', '    ld a, 7\n    ret\n').replace('without changing the caller registers or flags',
        'with the authored result in A and unchanged flags').replace('caller state is preserved', 'A holds seven')
    net.store.conn.execute("UPDATE functions SET status='asm' WHERE id=?", (fn['id'],))
    assert net.document_function(agent, slug, fn['name'], source).startswith('✅ DOCUMENTED:')
    return source


@TOOLS
@pytest.mark.parametrize('kind', ['c', 'asm'])
def test_actual_c_and_assembly_keep_research_through_resplit_and_archive_original_subject_on_rename(project, kind):
    net, slug = project
    agent, _ = net.local_agent('lifecycle_writer')
    source = accepted(net, slug, agent, kind)
    old = symbol(net, slug)
    record = put(net, slug, agent, 'symbol', value=annotation())['record']
    record = review(net, slug, 'symbol', old)['record']
    original = {key: record[key]['raw'] for key in ('annotation', 'evidence', 'subject')}
    before = history.capture(net, net.project_row(slug))
    split = net.resplit_banked(slug, apply=True, log=lambda *_: None)
    assert {key: net.store.one('SELECT * FROM symbols WHERE name=?', old)[key] for key in original} == original
    net.undo_resplit(slug, split['history_id'])
    assert history.capture(net, net.project_row(slug)) == before
    assert net.rename_symbol(agent, slug, old, 'RenamedProcedure').startswith('✅')
    fn = function(net, slug)
    assert fn['matched_source'] == source.replace(old, 'RenamedProcedure')
    assert net.inspect_annotations(slug, 'symbol', 'RenamedProcedure')['application'] == 'legacy_unknown'
    archive = net.store.one('SELECT * FROM notes WHERE text LIKE ? ORDER BY id DESC', archives.PREFIX + '%')
    assert {key: archive[key] for key in original} == original
    inspected = net.inspect_annotations(slug, 'note', archive['id'])
    assert inspected['application'] == 'archived'
    assert inspected['subject']['value']['entity']['symbol']['name'] == old
    assert inspected['subject']['value']['entity']['function']['name'] == old
    assert 'archived original research' in net.search_notes(slug, old)
    assert archives.PREFIX not in net.learnings(slug)
    net.resplit_banked(slug, apply=True, log=lambda *_: None)
    assert function(net, slug)['matched_source'] == source.replace(old, 'RenamedProcedure')


def test_split_and_merge_preserve_metadata_as_original_subject_without_inheriting_approval(project):
    net, slug = project
    agent, _ = net.local_agent('boundary_writer')
    old = symbol(net, slug)
    item = put(net, slug, agent, 'symbol', value=annotation())['record']
    original = item['subject']['raw']
    assert net.split_function(agent, slug, old, '0x0202', 'AuthoredTail').startswith('✅')
    assert net.inspect_annotations(slug, 'symbol', old)['application'] == 'legacy_unknown'
    archive = net.store.one('SELECT * FROM notes WHERE text LIKE ?', archives.PREFIX + '%')
    assert archive['subject'] == original
    assert net.merge_function(agent, slug, old).startswith('✅')
    assert net.inspect_annotations(slug, 'symbol', old)['application'] == 'legacy_unknown'
    assert net.store.one('SELECT COUNT(*) AS n FROM notes WHERE text LIKE ?', archives.PREFIX + '%')['n'] == 1


def test_idempotent_symbol_refresh_preserves_raw_future_metadata_and_changed_role_archives_it(project):
    net, slug = project
    pid, name = net.project_row(slug)['id'], symbol(net, slug)
    raw = ' { "version": 99, "future": [true, "original spelling"] } '
    net.store.conn.execute('UPDATE symbols SET annotation=?,evidence=?,subject=? WHERE name=?', (raw, raw, raw, name))
    row = net.store.one('SELECT * FROM symbols WHERE name=?', name)
    with net.store.tx() as db:
        symbol_records.save(db, pid, name, row['address'], row['size'], row['kind'])
    same = net.store.one('SELECT * FROM symbols WHERE name=?', name)
    assert all(same[key] == raw for key in ('annotation', 'evidence', 'subject'))
    with net.store.tx() as db:
        symbol_records.update(db, pid, name, kind='alias')
    assert all(net.store.one('SELECT * FROM symbols WHERE name=?', name)[key] is None for key in ('annotation', 'evidence', 'subject'))
    archive = net.store.one('SELECT * FROM notes WHERE text LIKE ?', archives.PREFIX + '%')
    assert all(archive[key] == raw for key in ('annotation', 'evidence', 'subject'))
    assert net.inspect_annotations(slug, 'note', archive['id'])['application'] == 'archived'


def test_rename_refuses_new_work_during_source_checks_and_preserves_the_new_observation(project, monkeypatch):
    net, slug = project
    agent, _ = net.local_agent('rename_race')
    old = symbol(net, slug)
    put(net, slug, agent, 'symbol', value=annotation())
    original = net.store.one('SELECT subject FROM symbols WHERE name=?', old)['subject']
    def changed(*_args, **_kwargs):
        net.add_note(agent, slug, 'A new observation while the source regression checks ran.')
        return []
    monkeypatch.setattr(net, 'regression_test', changed)
    with pytest.raises(NetworkError, match='work changed'):
        net.rename_symbol(agent, slug, old, 'NewName')
    assert net.store.one('SELECT subject FROM symbols WHERE name=?', old)['subject'] == original
    assert not net.store.one("SELECT 1 FROM symbols WHERE name='NewName'")
    assert net.store.one('SELECT text FROM notes')['text'].startswith('A new observation')


def test_research_status_is_visible_in_briefs_and_archives_stay_out_of_active_context(project):
    net, slug = project
    agent, _ = net.local_agent('brief_writer')
    name = symbol(net, slug)
    item = put(net, slug, agent, 'note', value=annotation(), function=name)['record']
    put(net, slug, agent, 'symbol', value=annotation())
    brief = net.get_function(name, slug)
    assert 'research hypothesis; pending_review; confidence low' in brief
    assert f'Symbol research for {name}: pending_review' in brief
    review(net, slug, 'note', item['key'])
    assert 'reviewed_research' in net.get_function(name, slug)
    with net.store.tx() as db:
        symbol_records.update(db, net.project_row(slug)['id'], name, kind='alias')
    assert archives.PREFIX not in net.get_function(name, slug)
