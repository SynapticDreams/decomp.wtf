"""Undo cannot restore unqualified acceptance or overwrite work added while source checks run."""
import time

import pytest

from decompnet.app import sms_resplit_source_check as checker, sms_resplit_undo_check as undo_check
from decompnet.network import NetworkError
from decompnet.rom import gb_build

from .test_sms_resplit_dependency_integration import project as fixture_project, included as fixture_included, SOURCE, row, capture

project, included = fixture_project, fixture_included


def accepted_resplit(net, slug):
    agent, _ = net.local_agent('fixture_writer')
    fn = row(net, slug)
    assert net.attempt(agent, fn['name'], SOURCE, slug)['matched']
    with net.store.tx() as db:
        db.execute('UPDATE functions SET vram=33280 WHERE id=?', (fn['id'],))
    return agent, net.resplit_banked(slug, apply=True, log=lambda *_: None)


@pytest.mark.skipif(not gb_build.available('z80'), reason='needs GBDK/SDCC')
@pytest.mark.parametrize('change', ['note', 'header', 'claim'])
def test_new_edits_during_undo_validation_prevent_restoring_over_them(included, change, monkeypatch):
    net, slug, header = included
    agent, result = accepted_resplit(net, slug)
    before = capture(net, slug)
    current, original = row(net, slug), checker.check
    calls = []
    def check(*args, **kwargs):
        assert not net.store.conn.in_transaction
        verdict = original(*args, **kwargs)
        assert verdict.state == 'passed'
        calls.append(True)
        if change == 'header':
            header.write_text('#define VALUE 8\n')
        else:
            with net.store.tx() as db:
                if change == 'note':
                    db.execute('INSERT INTO notes(project_id,text) VALUES(?,?)', (current['project_id'], 'A newer undo-time review.'))
                else:
                    db.execute('INSERT INTO claims VALUES(?,?,?,?)', (current['id'], agent.id, time.time(), time.time() + 300))
        return verdict
    monkeypatch.setattr(checker, 'check', check)
    with pytest.raises(NetworkError, match='newer work'):
        net.undo_resplit(slug, result['history_id'])
    assert calls and capture(net, slug)['tables']['functions'] == before['tables']['functions']
    assert net.resplit_history(slug)['history'][0]['undone_at'] is None
    if change == 'note':
        assert net.store.one('SELECT 1 FROM notes WHERE text=?', 'A newer undo-time review.')
    elif change == 'claim':
        assert net.store.one('SELECT 1 FROM claims WHERE function_id=?', current['id'])
    else:
        assert header.read_text() == '#define VALUE 8\n'


@pytest.mark.skipif(not gb_build.available('z80'), reason='needs GBDK/SDCC')
def test_undo_source_budget_never_restores_unverified_accepted_source(included, monkeypatch):
    net, slug, _header = included
    _agent, result = accepted_resplit(net, slug)
    before = capture(net, slug)
    monkeypatch.setattr(undo_check, 'MAX_CHECKS', 0)
    with pytest.raises(NetworkError, match='budget exhausted'):
        net.undo_resplit(slug, result['history_id'])
    assert capture(net, slug) == before and net.resplit_history(slug)['history'][0]['undone_at'] is None


@pytest.mark.skipif(not gb_build.available('z80'), reason='needs GBDK/SDCC')
def test_old_accepted_bytes_outside_the_frozen_input_cannot_be_restored(included):
    net, slug, _header = included
    agent, _ = net.local_agent('fixture_writer')
    fn = row(net, slug)
    assert net.attempt(agent, fn['name'], SOURCE, slug)['matched']
    with net.store.tx() as db:
        db.execute('UPDATE functions SET target=? WHERE id=?', (bytes.fromhex('3e08c9'), fn['id']))
    result = net.resplit_banked(slug, apply=True, log=lambda *_: None)
    assert row(net, slug)['matched_source'] == SOURCE
    before = capture(net, slug)
    with pytest.raises(NetworkError, match='not established in the frozen input'):
        net.undo_resplit(slug, result['history_id'])
    assert capture(net, slug) == before
