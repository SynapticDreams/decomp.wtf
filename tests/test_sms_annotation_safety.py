"""Bounded note/symbol facts reject forged authority and preserve new work across failed mutations."""
import copy
import sqlite3

import pytest

from decompnet.app import annotation_keys, sms_annotation_context as context
from decompnet.network import NetworkError
from decompnet.rom.annotations.evidence import binding
from .test_sms_annotation_subjects import project as fixture_project, put, review, TEXT
from .annotation_fixture import annotation

project = fixture_project


@pytest.mark.parametrize('kind', ['note', 'symbol'])
def test_metadata_write_and_review_failures_roll_back_archives_and_keep_new_work(project, monkeypatch, kind):
    net, slug = project
    agent, _ = net.local_agent('metadata_race')
    original = put(net, slug, agent, kind, value=annotation())['record']
    key = original['key']
    request = annotation(); request['target']['offset'] += 64
    before_count = net.store.one('SELECT COUNT(*) AS n FROM notes')['n']
    real = context.check_plan
    def changed(expected, actual, *, required=False):
        real(expected, actual, required=required)
        if required:
            net.add_note(agent, slug, 'A new observation before metadata application.')
    monkeypatch.setattr(context, 'check_plan', changed)
    with pytest.raises(NetworkError, match='changed'):
        put(net, slug, agent, kind, key=key, value=request)
    current = net.inspect_annotations(slug, kind, key)
    assert current['subject']['raw'] == original['subject']['raw']
    assert net.store.one('SELECT COUNT(*) AS n FROM notes')['n'] == before_count + 1
    monkeypatch.setattr(context, 'check_plan', real)
    def fail(*_args):
        raise NetworkError('authored metadata receipt failure')
    monkeypatch.setattr(net, '_event', fail)
    with pytest.raises(NetworkError, match='receipt failure'):
        put(net, slug, agent, kind, key=key, value=request)
    with pytest.raises(NetworkError, match='receipt failure'):
        review(net, slug, kind, key)
    assert net.inspect_annotations(slug, kind, key)['evidence']['raw'] == original['evidence']['raw']
    assert net.store.one('SELECT COUNT(*) AS n FROM notes')['n'] == before_count + 1


@pytest.mark.parametrize('kind', ['note', 'symbol'])
def test_review_reads_row_binding_and_guard_in_one_snapshot_for_other_database_connections(project, monkeypatch, kind):
    net, slug = project
    agent, _ = net.local_agent('atomic_metadata')
    item = put(net, slug, agent, kind, value=annotation())['record']
    path = net.store.conn.execute('PRAGMA database_list').fetchone()[2]
    fetch = annotation_keys.fetch
    attempts = []
    def racing(*args):
        row = fetch(*args)
        other = sqlite3.connect(path, timeout=0)
        try:
            with pytest.raises(sqlite3.OperationalError, match='locked'):
                other.execute('UPDATE notes SET text=? WHERE project_id=?', ('Unseen update', net.project_row(slug)['id']))
            attempts.append(True)
        finally:
            other.close()
        return row
    monkeypatch.setattr(annotation_keys, 'fetch', racing)
    net.review_annotation(slug, kind, item['key'], ok=True)
    net.inspect_annotations(slug, kind, item['key'])
    assert len(attempts) == 2


def test_copied_or_superseded_note_receipts_do_not_authorize_identical_new_subjects(project):
    net, slug = project
    agent, _ = net.local_agent('metadata_receipt')
    first = put(net, slug, agent, 'note', value=annotation())['record']
    approved = review(net, slug, 'note', first['key'])['record']
    second = put(net, slug, agent, 'note', value=annotation())['record']
    assert second['subject']['raw'] == approved['subject']['raw']
    net.store.conn.execute('UPDATE notes SET evidence=? WHERE id=?', (approved['evidence']['raw'], second['key']))
    assert net.inspect_annotations(slug, 'note', second['key'])['application'] == 'untrusted_review'
    review(net, slug, 'note', first['key'], ok=False)
    net.store.conn.execute('UPDATE notes SET evidence=? WHERE id=?', (approved['evidence']['raw'], first['key']))
    assert net.inspect_annotations(slug, 'note', first['key'])['application'] == 'untrusted_review'


@pytest.mark.parametrize('kind', ['note', 'symbol'])
def test_caller_review_receipts_and_tampered_future_subjects_are_not_accepted(project, kind):
    net, slug = project
    agent, _ = net.local_agent('forged_metadata')
    item = put(net, slug, agent, kind, value=annotation())['record']
    proof = copy.deepcopy(item['evidence']['value'])
    proof['review'] = {'state': 'accepted', 'actor': 'operator', 'at': 1, 'binding_sha256': binding(proof)}
    with pytest.raises(NetworkError, match='caller-supplied review'):
        put(net, slug, agent, kind, key=item['key'], value=annotation(), proof=proof)
    table, column = ('notes', 'id') if kind == 'note' else ('symbols', 'name')
    future = ' { "version": 99, "future": true } '
    net.store.conn.execute(f'UPDATE {table} SET subject=? WHERE {column}=?', (future, item['key']))
    inspected = net.inspect_annotations(slug, kind, item['key'])
    assert inspected['application'] == 'unsupported' and inspected['subject']['raw'] == future
    with pytest.raises(NetworkError, match='supported'):
        net.review_annotation(slug, kind, item['key'], ok=True)
    cleared = review(net, slug, kind, item['key'], clear=True)
    assert net.inspect_annotations(slug, 'note', cleared['archive_id'])['subject']['raw'] == future


def test_note_and_symbol_pages_are_complete_and_legacy_metadata_keeps_unknown_subjects(project):
    net, slug = project
    agent, _ = net.local_agent('metadata_pages')
    first = put(net, slug, agent, 'note')['record']
    second = put(net, slug, agent, 'note')['record']
    page = net.inspect_annotations(slug, 'note', limit=1)
    assert page['records'][0]['key'] == second['key'] and page['next_before'] == second['key']
    older = net.inspect_annotations(slug, 'note', before_id=page['next_before'], limit=1)
    assert older['records'][0]['key'] == first['key'] and older['next_before'] is None
    names, after = [], None
    while True:
        page = net.inspect_annotations(slug, 'symbol', after_symbol=after, limit=1)
        names += [row['key'] for row in page['records']]
        after = page['next_symbol']
        if after is None:
            break
    assert names == [row['name'] for row in net.store.all('SELECT name FROM symbols ORDER BY name')]
    net.store.conn.execute('UPDATE notes SET subject=NULL WHERE id=?', (first['key'],))
    unbound = net.inspect_annotations(slug, 'note', first['key'])
    assert unbound['application'] == 'unbound' and unbound['subject']['raw'] is None
    assert unbound['evidence']['raw'] == first['evidence']['raw']
    with pytest.raises(NetworkError):
        net.add_note(agent, slug, TEXT, note_id=first['key'], annotation=annotation(), evidence={'version': 99}, apply=False)
