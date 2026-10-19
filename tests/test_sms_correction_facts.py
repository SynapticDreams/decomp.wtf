"""Actual proposal, inspection, operator-review and undo workflows retain bound research claims."""
import copy
import json
from pathlib import Path

import pytest

from decompnet.app import correction_annotations, correction_receipts, sms_annotation_context
from decompnet.app.engine import RomNetwork
from decompnet.network import NetworkError
from decompnet.rom.annotations import dump
from decompnet.rom.annotations.evidence import binding
from decompnet.rom.annotations.payloads import KINDS
from .annotation_fixture import annotation, evidence
from .test_sms_resplit_source_check import project as fixture_project

project = fixture_project
WHY = 'The authored consumer reads this declared structure with the specified stride.'


def draft(kind='record'):
    value = annotation(kind)
    if kind == 'number':
        value['spec']['value'] = 0  # Authored fixture has zero padding here.
    return {'kind': kind, 'at': '00:0100' if kind in correction_annotations.policy.KINDS else '',
            'reason': WHY, 'annotation': value, 'evidence': evidence()}


def save(net, slug, agent, request=None):
    request = request or draft()
    preview = net.correct_split(agent, slug, **request, apply=False)
    return net.correct_split(agent, slug, **request, apply=True, expected_plan=preview['plan'])


def review(net, slug, cid, ok=True):
    preview = net.review_correction(slug, cid, ok)
    return net.review_correction(slug, cid, ok, apply=True, expected_plan=preview['plan'])


@pytest.mark.parametrize('kind', KINDS)
def test_every_kind_is_bound_pending_inspectable_and_undoable_after_reload(project, kind):
    net, slug = project
    agent, _ = net.local_agent('fact_writer')
    request = draft(kind)
    request['evidence']['origin'] = {'kind': 'operator', 'ref': 'caller-claim'}
    before = sms_annotation_context.guard(net, net.project_row(slug))
    preview = net.correct_split(agent, slug, **request, apply=False)
    assert not preview['applied'] and preview['correction']['binding'] == 'current'
    assert sms_annotation_context.guard(net, net.project_row(slug)) == before
    assert not net.store.all('SELECT * FROM corrections')
    applied = net.correct_split(agent, slug, **request, expected_plan=preview['plan'])
    item = applied['correction']
    assert item['application'] == 'pending_review' and not item['active']
    proof = item['evidence']['value']
    assert proof['origin'] == {'kind': 'agent', 'ref': f'agent:{agent.id}'}
    assert proof['revision']['platform'] == net.cfg(net.project_row(slug))['platform']
    assert proof['subject_sha256'] and proof['context']['sha256']
    raw = net.store.one('SELECT annotation,evidence FROM corrections')
    path = net.store.conn.execute('PRAGMA database_list').fetchone()[2]
    net.store.conn.close()
    loaded = RomNetwork(path, net.workspace)
    inspected = loaded.inspect_correction(slug, item['id'])
    assert inspected['annotation']['value'] == request['annotation'] and inspected['binding'] == 'current'
    assert inspected['evidence']['value'] == proof and not inspected['active']
    loaded.undo_correction(slug, item['id'])
    assert loaded.inspect_correction(slug, item['id'])['application'] == 'undone'
    assert tuple(loaded.store.one('SELECT annotation,evidence FROM corrections')) == tuple(raw)


@pytest.mark.parametrize('kind', KINDS)
def test_operator_review_is_separate_from_recording_and_only_legacy_kinds_feed_hints(project, kind):
    net, slug = project
    agent, _ = net.local_agent('review_fixture')
    cid = save(net, slug, agent, draft(kind))['correction']['id']
    previous = sms_annotation_context.guard(net, net.project_row(slug))
    preview = net.review_correction(slug, cid, True)
    assert sms_annotation_context.guard(net, net.project_row(slug)) == previous
    approved = net.review_correction(slug, cid, True, apply=True, expected_plan=preview['plan'])['correction']
    legacy = kind in correction_annotations.policy.KINDS
    assert approved['review'] == 'accepted' and approved['active'] is legacy
    assert approved['application'] == ('legacy_hint' if legacy else 'awaiting_consumer')
    assert correction_receipts.trusted(net, net.store.one('SELECT * FROM corrections'))
    rejected = review(net, slug, cid, False)['correction']
    assert rejected['review'] == 'rejected' and not rejected['active']


def test_caller_receipts_and_database_claims_do_not_authenticate_operator_review(project):
    net, slug = project
    agent, _ = net.local_agent('receipt_fixture')
    request = draft('code')
    preview = net.correct_split(agent, slug, **request, apply=False)
    proof = preview['correction']['evidence']['value']
    proof['review'] = {'state': 'accepted', 'actor': 'operator', 'at': 1, 'binding_sha256': binding(proof)}
    with pytest.raises(NetworkError, match='caller-supplied review'):
        net.correct_split(agent, slug, **{**request, 'evidence': proof}, apply=False)
    cid = save(net, slug, agent, request)['correction']['id']
    with net.store.tx() as db:
        db.execute('UPDATE corrections SET evidence=? WHERE id=?', (dump(proof), cid))
    assert net.inspect_correction(slug, cid)['application'] == 'untrusted_review'
    assert not net._hints(net.project_row(slug))['entries']
    review(net, slug, cid)
    assert net._hints(net.project_row(slug))['entries'] == {0x100: 0x100}
    with net.store.tx() as db:
        db.execute("UPDATE corrections SET reason='Changed after operator review' WHERE id=?", (cid,))
    assert net.inspect_correction(slug, cid)['application'] == 'untrusted_review'
    assert not net._hints(net.project_row(slug))['entries']


@pytest.mark.parametrize('change', ['note', 'correction', 'profile', 'input'])
def test_stale_proposals_never_publish_over_new_work_or_changed_inputs(project, change):
    net, slug = project
    agent, _ = net.local_agent('stale_fixture')
    request = draft()
    preview = net.correct_split(agent, slug, **request, apply=False)
    if change == 'note':
        net.add_note(agent, slug, 'An authored concurrent observation.')
    elif change == 'correction':
        net.correct_split(agent, slug, 'code', '00:0100', WHY)
    elif change == 'profile':
        net.sms.configure(slug, 'sega', 'annotated-original', 'A changed authored mapping evidence declaration.')
    else:
        proj = net.project_row(slug)
        path = Path(proj['root']) / net.cfg(proj)['rom']['file']
        raw = bytearray(path.read_bytes()); raw[0x100] ^= 1; path.write_bytes(raw)
    before = net.store.one('SELECT COUNT(*) AS n FROM corrections')['n']
    with pytest.raises(NetworkError):
        net.correct_split(agent, slug, **request, expected_plan=preview['plan'])
    assert net.store.one('SELECT COUNT(*) AS n FROM corrections')['n'] == before


def test_new_edits_in_the_apply_window_survive_and_failed_publication_rolls_back(project, monkeypatch):
    net, slug = project
    agent, _ = net.local_agent('race_fixture')
    request = draft()
    preview = net.correct_split(agent, slug, **request, apply=False)
    real = sms_annotation_context.check_plan
    def edited(*args, **kwargs):
        real(*args, **kwargs)
        net.add_note(agent, slug, 'A newer observation in the apply window.')
    monkeypatch.setattr(sms_annotation_context, 'check_plan', edited)
    with pytest.raises(NetworkError, match='changed'):
        net.correct_split(agent, slug, **request, expected_plan=preview['plan'])
    assert net.store.one('SELECT text FROM notes')['text'].startswith('A newer')
    assert not net.store.all('SELECT * FROM corrections')
    monkeypatch.setattr(sms_annotation_context, 'check_plan', real)
    preview = net.correct_split(agent, slug, **request, apply=False)
    def failed(*_args):
        raise NetworkError('authored publication failure')
    monkeypatch.setattr(net, '_event', failed)
    with pytest.raises(NetworkError, match='publication failure'):
        net.correct_split(agent, slug, **request, expected_plan=preview['plan'])
    assert not net.store.all('SELECT * FROM corrections')


def test_changed_mapping_unavailable_input_and_unsupported_metadata_remain_inspectable(project):
    net, slug = project
    agent, _ = net.local_agent('inspection_fixture')
    cid = save(net, slug, agent)['correction']['id']
    review(net, slug, cid)
    net.sms.configure(slug, 'sega', 'annotated-original', 'Different evidence for the same authored wiring model.')
    assert net.inspect_correction(slug, cid)['application'] == 'stale'
    with pytest.raises(NetworkError, match='stale'):
        net.review_correction(slug, cid, True)
    for raw, expected in [('{"version":99,"future":true}', 'unsupported'), ('{', 'invalid'), ('x' * 70000, 'invalid'),
                          ('{"version":99,"future":"' + '字' * 22000 + '"}', 'invalid')]:
        net.store.conn.execute('UPDATE corrections SET annotation=? WHERE id=?', (raw, cid))
        inspected = net.inspect_correction(slug, cid)
        assert inspected['application'] == expected and not inspected['active']
        assert inspected['annotation']['raw'] == (raw[:4096] if len(raw.encode()) > 65536 else raw)
    assert not net._hints(net.project_row(slug))['data']


def test_paged_history_and_agent_tool_keep_review_authority_outside_worker_tools(project):
    from decompnet.app import tools, agents
    net, slug = project
    agent, _ = net.local_agent('tools_fixture')
    first = save(net, slug, agent)['correction']['id']
    second = save(net, slug, agent)['correction']['id']
    page = json.loads(tools.call(net, agent, slug, 'inspect_corrections', {'limit': 1}))
    assert page['next_before'] == second and page['corrections'][0]['id'] == second
    next_page = net.corrections(slug, before_id=page['next_before'], limit=1)
    assert next_page['corrections'][0]['id'] == first and next_page['next_before'] is None
    result = json.loads(tools.call(net, agent, slug, 'correct_split', {**draft(), 'apply': False}))
    assert not result['applied']
    assert 'review_correction' not in tools.HANDLERS
    names = {item['function']['name'] for item in agents.api_tool_schemas()}
    assert 'inspect_corrections' in names and 'review_correction' not in names
    assert 'inspect_corrections' not in tools.tool_names(fork=True)


@pytest.mark.parametrize('changed', ['revision', 'context', 'subject', 'ram', 'location', 'number'])
def test_wrong_revision_context_subject_or_coordinates_cannot_publish(project, changed):
    net, slug = project
    agent, _ = net.local_agent('binding_fixture')
    request = draft('number' if changed == 'number' else 'record')
    preview = net.correct_split(agent, slug, **request, apply=False)
    proof = copy.deepcopy(preview['correction']['evidence']['value'])
    if changed in ('revision', 'context'):
        proof[changed]['sha256'] = 'e' * 64
    elif changed == 'subject':
        proof['subject_sha256'] = 'e' * 64
    elif changed == 'ram':
        request['annotation']['target']['space'] = 'wram'
    elif changed == 'location':
        request['at'] = '00:0200'
    else:
        request['annotation']['spec']['value'] = 1
    with pytest.raises(NetworkError):
        net.correct_split(agent, slug, **{**request, 'evidence': proof}, apply=False)
    assert not net.store.all('SELECT * FROM corrections')
