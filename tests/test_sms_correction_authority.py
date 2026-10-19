"""Cross-connection snapshot isolation, review rollback and real MCP validation protect operator authority."""
import asyncio
import json
import sqlite3

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from decompnet.app import correction_records, sms_annotation_context, tools
from decompnet.network import NetworkError
from .test_sms_correction_facts import project as fixture_project, draft, save, review

project = fixture_project


def test_review_and_inspection_hold_one_database_snapshot_against_other_connections(project, monkeypatch):
    net, slug = project
    agent, _ = net.local_agent('atomic_reader')
    cid = save(net, slug, agent)['correction']['id']
    path = net.store.conn.execute('PRAGMA database_list').fetchone()[2]
    attempted = []
    one = correction_records.one
    def racing(*args):
        row = one(*args)
        other = sqlite3.connect(path, timeout=0)
        try:
            with pytest.raises(sqlite3.OperationalError, match='locked'):
                other.execute("UPDATE corrections SET reason='Unseen replacement evidence' WHERE id=?", (cid,))
            attempted.append(True)
        finally:
            other.close()
        return row
    monkeypatch.setattr(correction_records, 'one', racing)
    net.review_correction(slug, cid, True)
    net.inspect_correction(slug, cid)
    assert len(attempted) == 2
    assert net.store.one('SELECT reason FROM corrections')['reason'] == draft()['reason']


def test_review_checks_new_work_and_rolls_back_a_failed_authority_event(project, monkeypatch):
    net, slug = project
    agent, _ = net.local_agent('review_race')
    cid = save(net, slug, agent, draft('code'))['correction']['id']
    preview = net.review_correction(slug, cid, True)
    original = net.store.one('SELECT evidence FROM corrections')['evidence']
    check = sms_annotation_context.check_plan
    def changed(*args, **kwargs):
        check(*args, **kwargs)
        net.add_note(agent, slug, 'New work during operator review application.')
    monkeypatch.setattr(sms_annotation_context, 'check_plan', changed)
    with pytest.raises(NetworkError, match='changed'):
        net.review_correction(slug, cid, True, apply=True, expected_plan=preview['plan'])
    assert net.store.one('SELECT evidence FROM corrections')['evidence'] == original
    assert net.store.one('SELECT text FROM notes')['text'].startswith('New work')
    monkeypatch.setattr(sms_annotation_context, 'check_plan', check)
    preview = net.review_correction(slug, cid, True)
    def fail(*_args):
        raise NetworkError('authored receipt failure')
    monkeypatch.setattr(net, '_event', fail)
    with pytest.raises(NetworkError, match='receipt failure'):
        net.review_correction(slug, cid, True, apply=True, expected_plan=preview['plan'])
    assert net.store.one('SELECT evidence FROM corrections')['evidence'] == original
    assert not net.store.all("SELECT * FROM events WHERE kind='correction_review'")
    assert not net._hints(net.project_row(slug))['entries']


def test_a_receipt_cannot_authorize_a_different_record_or_restore_superseded_approval(project):
    net, slug = project
    agent, _ = net.local_agent('receipt_copy')
    first = save(net, slug, agent, draft('code'))['correction']['id']
    reviewed = review(net, slug, first)['correction']
    raw = reviewed['evidence']['raw']
    second = save(net, slug, agent, draft('code'))['correction']['id']
    net.store.conn.execute('UPDATE corrections SET evidence=? WHERE id=?', (raw, second))
    assert net.inspect_correction(slug, second)['application'] == 'untrusted_review'
    review(net, slug, first, False)
    net.store.conn.execute('UPDATE corrections SET evidence=? WHERE id=?', (raw, first))
    assert net.inspect_correction(slug, first)['application'] == 'untrusted_review'


def test_actual_mcp_preview_is_structured_and_rejects_boolean_counts_or_numeric_apply_flags(project):
    net, slug = project
    agent, _ = net.local_agent('mcp_fixture')
    mcp = tools.build_mcp(net, lambda _context: (agent, slug))
    async def exercise():
        names = {item.name for item in await mcp.list_tools()}
        assert 'inspect_corrections' in names and 'review_correction' not in names
        result = await mcp.call_tool('correct_split', {**draft(), 'apply': False})
        assert not result.is_error
        parsed = json.loads(result.content[0].text)
        assert not parsed['applied'] and parsed['correction']['review'] == 'pending'
        for arguments in ({'count': True}, {'apply': 1}, {'count': 1.5}):
            with pytest.raises(ToolError):
                await mcp.call_tool('correct_split', {**draft('data'), 'apply': False, **arguments})
    asyncio.run(exercise())
    assert not net.store.all('SELECT * FROM corrections')


def test_readonly_inspection_survives_an_unavailable_work_guard_without_granting_authority(project, monkeypatch):
    net, slug = project
    agent, _ = net.local_agent('bounded_reader')
    cid = save(net, slug, agent)['correction']['id']
    def exhausted(*_args):
        raise NetworkError('authored snapshot budget exhausted')
    monkeypatch.setattr(sms_annotation_context, 'guard', exhausted)
    result = net.inspect_correction(slug, cid)
    assert result['annotation']['value'] == draft()['annotation']
    assert result['inspection_context'] is None and result['inspection_guard'] == 'unavailable'
    assert not result['active']
    with pytest.raises(NetworkError, match='budget exhausted'):
        net.review_correction(slug, cid, True)
