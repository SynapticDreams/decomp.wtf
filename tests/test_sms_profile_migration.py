"""Proposed SMS/GG profiles revalidate preserved work and commit model/layout/history together."""
import copy
import json
from pathlib import Path
import time

import pytest

from decompnet.app import banked_resplit_history as history
from decompnet.network import NetworkError
from decompnet.rom import gb_build, sms, sms_asm

from .test_sms_resplit_source_check import project as fixture_project, C

project = fixture_project
REASON = 'The authored fixture specifies fixed cartridge ROM wiring for this model.'


def proposal(mapper='mapperless', **values):
    return {'mapper': mapper, 'variant': 'annotated-original', 'reason': REASON, **values}


def snapshot(net, slug):
    return history.capture(net, net.project_row(slug))


def function(net, slug):
    return net.store.one('SELECT * FROM functions WHERE project_id=? AND rom_offset=512', net.project_row(slug)['id'])


@pytest.mark.skipif(not gb_build.available('z80'), reason='needs GBDK/SDCC')
@pytest.mark.parametrize('mapper', ['mapperless', 'codemasters'])
def test_proposed_model_revalidates_unchanged_c_and_undo_restores_the_old_model(project, mapper, monkeypatch):
    net, slug = project
    agent, _ = net.local_agent('fixture_writer')
    fn = function(net, slug)
    assert net.attempt(agent, fn['name'], C, slug)['matched']
    before = snapshot(net, slug)
    with pytest.raises(NetworkError, match='requires revalidation'):
        net.sms.configure(slug, **proposal(mapper))
    observed, original = [], sms.split
    def split(*args, **kwargs):
        observed.append(kwargs['hints']['mapper'])
        return original(*args, **kwargs)
    monkeypatch.setattr(sms, 'split', split)
    requested = proposal(mapper)
    preview = net.resplit_banked(slug, profile=requested, log=lambda *_: None)
    assert observed == [mapper] and snapshot(net, slug) == before
    assert preview['profile_transition']['proposed']['mapper'] == mapper
    assert preview['source_revalidation_pending'] == 1 and preview['removed'] == 0
    applied = net.resplit_banked(slug, apply=True, expected_plan=preview['plan'], profile=requested, log=lambda *_: None)
    assert observed == [mapper, mapper]
    after = snapshot(net, slug)
    current = function(net, slug)
    assert current['id'] == fn['id'] and current['matched_source'] == C and current['status'] == 'matched'
    assert json.loads(current['meta'])['resplit_validation']['checked_plan'] == preview['plan']
    assert applied['source_revalidation']['passed'] == 1
    cfg = net.cfg(net.project_row(slug))
    assert cfg['sms_profile']['mapper'] == mapper
    assert cfg['rom'] == json.loads(before['project']['config'])['rom']
    assert after['tables']['attempts'] == before['tables']['attempts']
    summary = net.resplit_history(slug)['history'][0]['summary']
    assert summary['profile_transition'] == preview['profile_transition'] and summary['plan'] == preview['plan']
    net.undo_resplit(slug, applied['history_id'])
    assert snapshot(net, slug) == before


@pytest.mark.parametrize('payload', [{}, {'mapper': 'mapperless'}, proposal('unknown'), proposal('unsupported'),
    proposal(variant='bad'), proposal(reason='short'), proposal(False), {**proposal(), 'extra': 'unexpected'}])
def test_invalid_or_unsupported_proposal_never_saves_a_profile(project, payload):
    net, slug = project
    before = snapshot(net, slug)
    with pytest.raises(NetworkError):
        net.resplit_banked(slug, profile=payload, log=lambda *_: None)
    assert snapshot(net, slug) == before and not net.resplit_history(slug)['history']


def test_apply_requires_the_proposal_fingerprint_and_rejects_edited_proposals(project):
    net, slug = project
    before = snapshot(net, slug)
    requested = proposal()
    with pytest.raises(NetworkError, match='preview this profile migration'):
        net.resplit_banked(slug, profile=requested, apply=True, log=lambda *_: None)
    preview = net.resplit_banked(slug, profile=requested, log=lambda *_: None)
    with pytest.raises(NetworkError, match='stale'):
        net.resplit_banked(slug, profile=proposal('codemasters'), expected_plan=preview['plan'], apply=True, log=lambda *_: None)
    with pytest.raises(NetworkError, match='stale'):
        net.resplit_banked(slug, profile=proposal(reason=REASON + ' Additional evidence.'), expected_plan=preview['plan'], apply=True, log=lambda *_: None)
    assert snapshot(net, slug) == before


@pytest.mark.parametrize('failure', ['classification', 'commit'])
def test_failed_apply_keeps_original_profile_work_and_history(project, failure, monkeypatch):
    net, slug = project
    before = snapshot(net, slug)
    requested = proposal()
    preview = net.resplit_banked(slug, profile=requested, log=lambda *_: None)
    if failure == 'classification':
        def fail(*_):
            raise RuntimeError('authored failure after proposed config update')
        monkeypatch.setattr(history, 'mark_sms', fail)
    else:
        with net.store.tx() as db:
            db.execute('CREATE TABLE migration_guard(id INTEGER PRIMARY KEY)')
            db.execute('CREATE TABLE migration_fk(id INTEGER REFERENCES migration_guard DEFERRABLE INITIALLY DEFERRED)')
            db.execute("CREATE TRIGGER migration_bad AFTER UPDATE OF config ON projects BEGIN INSERT INTO migration_fk VALUES(1); END")
    with pytest.raises(Exception, match='authored failure|FOREIGN KEY'):
        net.resplit_banked(slug, profile=requested, expected_plan=preview['plan'], apply=True, log=lambda *_: None)
    assert snapshot(net, slug) == before and not net.resplit_history(slug)['history']
    assert not net.store.conn.in_transaction


def test_profile_transition_blocks_claims_on_unchanged_open_work(project):
    net, slug = project
    fn = function(net, slug)
    agent, _ = net.local_agent('fixture_reader')
    with net.store.tx() as db:
        db.execute('INSERT INTO claims VALUES(?,?,?,?)', (fn['id'], agent.id, time.time(), time.time() + 300))
    before = snapshot(net, slug)
    preview = net.resplit_banked(slug, profile=proposal(), log=lambda *_: None)
    with pytest.raises(NetworkError, match='release claims'):
        net.resplit_banked(slug, profile=proposal(), expected_plan=preview['plan'], apply=True, log=lambda *_: None)
    assert snapshot(net, slug) == before


@pytest.mark.skipif(not sms_asm.available(), reason='needs WLA-DX')
def test_assembly_is_rejudged_in_the_new_model_with_semantic_review_pending(project, monkeypatch):
    from .test_sms import make_rom

    net, _original_slug = project
    platform = net.cfg(net.project_row(_original_slug))['platform']
    image = make_rom(region=4 if platform == 'sms' else 6,
                     code={0: bytes.fromhex('cd0002 18fe'), 512: bytes.fromhex('3e01 32ffff c9')})
    slug = net.import_rom(image, name=f'bank-write.{platform}', confirmed=True, log=lambda *_: None)
    net.sms.configure(slug, 'sega', 'annotated-original', REASON)
    fn = function(net, slug)
    with net.store.tx() as db:
        db.execute("UPDATE functions SET status='asm' WHERE id=?", (fn['id'],))
    agent, _ = net.local_agent('fixture_writer')
    source = ('; Selects the authored cartridge bank for the third CPU window.\n'
              '; Input: none. Output: A and the selector hold one; flags are preserved.\n'
              'SelectWindowBank:\n    ld a, 1\n    ld (MapperSlot2), a\n    ret\n')
    accepted = net.document_function(agent, slug, fn['name'], source)
    assert accepted.startswith('✅ DOCUMENTED:'), accepted
    before = snapshot(net, slug)
    models, original = [], sms_asm.judge
    def judge(routine, *args, **kwargs):
        models.append(routine.mapper)
        return original(routine, *args, **kwargs)
    monkeypatch.setattr(sms_asm, 'judge', judge)
    preview = net.resplit_banked(slug, profile=proposal(), log=lambda *_: None)
    assert preview['source_revalidation_pending'] == 1 and not models
    applied = net.resplit_banked(slug, profile=proposal(), expected_plan=preview['plan'], apply=True, log=lambda *_: None)
    current = function(net, slug)
    assert current['target'] == fn['target'] and current['id'] == fn['id']
    assert models == ['mapperless'] and applied['source_revalidation']['passed'] == 1
    assert current['matched_source'] and 'MapperSlot2' in current['matched_source']
    assert json.loads(current['meta'])['resplit_validation']['semantic_review'] == 'pending'
    assert json.loads(current['meta'])['sample']  # The legacy address alias does not approve the old purpose.
    assert net.cfg(net.project_row(slug))['sms_profile']['mapper'] == 'mapperless'
    net.undo_resplit(slug, applied['history_id'])
    assert snapshot(net, slug) == before


@pytest.mark.parametrize('edit', ['note', 'profile', 'sidecar'])
def test_concurrent_edits_while_discovering_proposed_layout_refuse_apply(project, edit, monkeypatch):
    net, slug = project
    before = snapshot(net, slug)
    requested = proposal()
    preview = net.resplit_banked(slug, profile=requested, log=lambda *_: None)
    original = sms.split
    def split(*args, **kwargs):
        functions = original(*args, **kwargs)
        if edit == 'sidecar':
            cfg = net.cfg(net.project_row(slug))
            (Path(net.project_row(slug)['root']) / cfg['rom']['file']).with_suffix('.sym').write_text('00:0200 NewObservedEntry\n')
        else:
            with net.store.tx() as db:
                if edit == 'note':
                    db.execute('INSERT INTO notes(project_id,text) VALUES(?,?)', (net.project_row(slug)['id'], 'Concurrent review.'))
                else:
                    cfg = net.cfg(net.project_row(slug))
                    cfg['sms_profile']['reason'] = REASON + ' A competing profile edit.'
                    db.execute('UPDATE projects SET config=? WHERE id=?', (json.dumps(cfg), net.project_row(slug)['id']))
        return functions
    monkeypatch.setattr(sms, 'split', split)
    with pytest.raises(NetworkError, match='changed'):
        net.resplit_banked(slug, profile=requested, expected_plan=preview['plan'], apply=True, log=lambda *_: None)
    assert snapshot(net, slug)['tables']['functions'] == before['tables']['functions']
    assert not net.resplit_history(slug)['history']


def test_legacy_proposal_binds_identity_only_on_apply_and_undo_restores_it(project):
    net, slug = project
    proj = net.project_row(slug)
    cfg = copy.deepcopy(net.cfg(proj))
    cfg['rom'].pop('identity', None)
    cfg.pop('sms_profile', None)
    with net.store.tx() as db:
        db.execute('UPDATE projects SET config=? WHERE id=?', (json.dumps(cfg), proj['id']))
    before = snapshot(net, slug)
    preview = net.resplit_banked(slug, profile=proposal(), log=lambda *_: None)
    assert snapshot(net, slug) == before
    applied = net.resplit_banked(slug, profile=proposal(), expected_plan=preview['plan'], apply=True, log=lambda *_: None)
    current = net.cfg(net.project_row(slug))
    assert current['rom']['identity']['normalized']['sha256'] == current['sms_profile']['sha256']
    net.undo_resplit(slug, applied['history_id'])
    assert snapshot(net, slug) == before


@pytest.mark.skipif(not sms_asm.available(), reason='needs WLA-DX')
def test_old_documented_entry_without_new_model_placement_is_archived_unaccepted(project):
    from .test_sms import make_rom
    from decompnet.app import banked_resplit_archive as archive

    net, original_slug = project
    platform = net.cfg(net.project_row(original_slug))['platform']
    image = make_rom(region=4 if platform == 'sms' else 6,
        code={0: bytes.fromhex('3e01 32ffff cd0082 18fe'), 0x4200: b'\xc9'})
    slug = net.import_rom(image, name=f'mapped-leaf.{platform}', confirmed=True, log=lambda *_: None)
    net.sms.configure(slug, 'sega', 'annotated-original', REASON)
    proj = net.project_row(slug)
    fn = net.store.one('SELECT * FROM functions WHERE project_id=? AND rom_offset=?', proj['id'], 0x4200)
    assert fn is not None and fn['vram'] == 0x8200
    with net.store.tx() as db:
        db.execute("UPDATE functions SET status='asm' WHERE id=?", (fn['id'],))
    agent, _ = net.local_agent('fixture_writer')
    source = ('; Returns to its caller with the caller registers and flags preserved.\n'
              '; Input: caller state. Output: unchanged caller state.\nWindowLeaf:\n    ret\n')
    assert net.document_function(agent, slug, fn['name'], source).startswith('✅ DOCUMENTED:')
    before = snapshot(net, slug)
    preview = net.resplit_banked(slug, profile=proposal(), log=lambda *_: None)
    applied = net.resplit_banked(slug, profile=proposal(), expected_plan=preview['plan'], apply=True, log=lambda *_: None)
    assert applied['source_revalidation']['unresolved'] == 1
    assert not net.store.one('SELECT 1 FROM functions WHERE project_id=? AND rom_offset=?', proj['id'], 0x4200)
    recovered = archive.read(net, slug, applied['history_id'], function_id=fn['id'], item='accepted')
    assert recovered['text'].strip() == source.strip()
    net.undo_resplit(slug, applied['history_id'])
    assert snapshot(net, slug) == before


@pytest.mark.skipif(not gb_build.available('z80'), reason='needs GBDK/SDCC')
def test_unavailable_tools_leave_retained_source_as_a_draft_under_the_proposed_model(project, monkeypatch):
    net, slug = project
    fn = function(net, slug)
    agent, _ = net.local_agent('fixture_writer')
    assert net.attempt(agent, fn['name'], C, slug)['matched']
    preview = net.resplit_banked(slug, profile=proposal(), log=lambda *_: None)
    monkeypatch.setattr(gb_build, 'available', lambda *_: False)
    result = net.resplit_banked(slug, profile=proposal(), expected_plan=preview['plan'], apply=True, log=lambda *_: None)
    current = function(net, slug)
    assert current['matched_source'] is None and current['best_source'] == C
    assert current['best_score'] is None and result['source_revalidation']['unresolved'] == 1
    assert net.cfg(net.project_row(slug))['sms_profile']['mapper'] == 'mapperless'
