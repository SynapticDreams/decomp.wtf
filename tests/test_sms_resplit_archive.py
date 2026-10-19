"""Forward recovery is revision-bound, paged and read-only even after whole-split undo becomes unsafe."""
import hashlib
import json
import time

import pytest

from decompnet.app import banked_resplit_archive as archive, banked_resplit_history as history, banked_resplit_state as state
from decompnet.network import NetworkError
from decompnet.rom import gb_build, sms_asm

from .test_sms import make_rom
from .test_sms_resplit_source_check import project as fixture_project, C, ASM

project = fixture_project


def capture(net, slug):
    return history.capture(net, net.project_row(slug))


def function(net, slug):
    return net.store.one('SELECT * FROM functions WHERE project_id=? AND rom_offset=512', net.project_row(slug)['id'])


@pytest.mark.skipif(not gb_build.available('z80') or not sms_asm.available(), reason='needs pinned GBDK and WLA-DX')
@pytest.mark.parametrize('kind', ['c', 'asm'])
def test_saved_source_can_be_recovered_and_rejudged_after_new_work_blocks_undo(project, kind):
    net, slug = project
    fn, proj = function(net, slug), net.project_row(slug)
    agent, _ = net.local_agent('fixture_archivist')
    source = C if kind == 'c' else ASM.replace('    ret\n', '    ld a, 7\n    ret\n').replace(
        'without changing the caller registers or flags', 'with the authored result in A and unchanged flags').replace(
        'caller state is preserved', 'A holds the authored result')
    if kind == 'c':
        assert net.attempt(agent, fn['name'], source, slug)['matched']
    else:
        with net.store.tx() as db:
            db.execute("UPDATE functions SET status='asm' WHERE id=?", (fn['id'],))
        assert net.document_function(agent, slug, fn['name'], source).startswith('✅ DOCUMENTED:')
    with net.store.tx() as db:
        db.execute('UPDATE functions SET vram=33280 WHERE id=?', (fn['id'],))
        db.execute('INSERT INTO notes(project_id,function_id,agent_id,text) VALUES(?,?,?,?)',
                   (proj['id'], fn['id'], agent.id, 'Original authored evidence.'))
    old = dict(function(net, slug))
    saved = net.resplit_banked(slug, apply=True, log=lambda *_: None)
    current = function(net, slug)
    assert current['id'] != old['id']
    with net.store.tx() as db:
        db.execute('INSERT INTO notes(project_id,function_id,text) VALUES(?,?,?)',
                   (proj['id'], current['id'], 'New review after resplit.'))
        db.execute('INSERT INTO claims VALUES(?,?,?,?)', (current['id'], agent.id, time.time(), time.time() + 300))
        db.execute('UPDATE functions SET best_source=? WHERE id=?', ('A newer saved draft.', current['id']))
    before = capture(net, slug)
    with pytest.raises(NetworkError, match='newer work'):
        net.undo_resplit(slug, saved['history_id'])
    listing = archive.read(net, slug, saved['history_id'])
    record = next(row for row in listing['functions'] if row['id'] == old['id'])
    assert record['target_sha256'] == hashlib.sha256(old['target']).hexdigest() and record['vram'] == 0x8200
    assert listing['origin']['normalized'] == {**net.cfg(proj)['rom']['identity']['normalized'], 'fields_truncated': []}
    options = archive.read(net, slug, saved['history_id'], function_id=old['id'])['items']
    attempt = next(item for item in options if item['key'].startswith('attempt:'))
    assert attempt['provenance']['agent_id'] == agent.id and attempt['provenance']['score'] == 0
    assert attempt['provenance']['context_version'] is not None
    selected = archive.read(net, slug, saved['history_id'], function_id=old['id'], item='accepted')
    assert selected['text'] == old['matched_source'] and selected['next_start'] is None
    assert selected['sha256'] == hashlib.sha256(selected['text'].encode()).hexdigest()
    assert selected['filename'].endswith('.asm' if kind == 'asm' else '.c')
    if kind == 'asm':
        assert sms_asm.judge(net._routine(proj, current), selected['text']).ok
    else:
        header = net._context(proj['id'], current['unit'])['header']
        built = gb_build.compile_function(selected['text'], current['name'], arch='z80', context_header=header)
        assert built.code == bytes(current['target'])
    note = next(item for item in options if item['key'].startswith('note:'))
    assert archive.read(net, slug, saved['history_id'], function_id=old['id'], item=note['key'])['text'] == 'Original authored evidence.'
    assert 'Original authored evidence.' not in json.dumps(listing)
    assert old['matched_source'] not in json.dumps(net.resplit_history(slug))
    assert capture(net, slug) == before and not net.store.conn.in_transaction


@pytest.fixture
def saved(project):
    net, slug = project
    fn = function(net, slug)
    text = ('draft 😀 café\n' * 3000) + 'complete'
    with net.store.tx() as db:
        db.execute('UPDATE functions SET best_source=? WHERE id=?', (text, fn['id']))
        for index in range(30):
            db.execute('INSERT INTO attempts(function_id,source,score,agent_id,context_version) VALUES(?,?,?,1,1)',
                       (fn['id'], f'authored attempt {index}', index))
            db.execute('INSERT INTO functions(project_id,name,rom_offset,vram,size,target,unit) VALUES(?,?,?,?,1,?,?)',
                       (fn['project_id'], f'Archived_{index}', 0x1000 + index, 0x1000 + index, b'\xc9', 'bank000'))
    result = net.resplit_banked(slug, apply=True, log=lambda *_: None)
    return net, slug, result['history_id'], fn['id'], text


def pages(net, slug, hid, field, **kwargs):
    offset, out = 0, []
    while offset is not None:
        result = archive.read(net, slug, hid, offset=offset, **kwargs)
        assert len(result[field]) <= archive.PAGE
        out.extend(result[field])
        offset = result['next_offset']
    assert len(out) == result['total']
    return out


def test_metadata_and_unicode_text_pages_recover_complete_saved_work(saved):
    net, slug, hid, fid, text = saved
    before = capture(net, slug)
    functions = pages(net, slug, hid, 'functions')
    assert len(functions) > archive.PAGE and len({row['id'] for row in functions}) == len(functions)
    items = pages(net, slug, hid, 'items', function_id=fid)
    assert len({item['key'] for item in items}) == len(items) > archive.PAGE
    assert len([item for item in items if item['key'].startswith('attempt:')]) == 30
    assert text not in json.dumps(items) and 'authored attempt 29' not in json.dumps(items)
    chunks, start = [], 0
    while start is not None:
        part = archive.read(net, slug, hid, function_id=fid, item='best', start=start, limit=10000)
        assert part['start'] == start and len(part['text']) <= 10000
        chunks.append(part['text'])
        start = part['next_start']
    assert ''.join(chunks) == text and part['sha256'] == hashlib.sha256(text.encode()).hexdigest()
    for key in ('compiler', 'symbols', 'review', 'header:1'):
        part = archive.read(net, slug, hid, function_id=fid, item=key)
        assert part['next_start'] is None and part['characters'] == len(part['text'])
    assert capture(net, slug) == before


@pytest.mark.parametrize('kwargs', [{'history_id': True}, {'history_id': 0}, {'history_id': 2**63},
    {'function_id': -1}, {'function_id': '1e3'}, {'offset': -1}, {'offset': 100001}, {'offset': True},
    {'start': -1}, {'start': 1}, {'item': 'best'}, {'item': '../../source'}, {'limit': 0}, {'limit': 262145}])
def test_invalid_archive_selection_never_mutates_live_work(saved, kwargs):
    net, slug, hid, _fid, _text = saved
    before = capture(net, slug)
    with pytest.raises(NetworkError):
        archive.read(net, slug, **{'history_id': hid, **kwargs})
    assert capture(net, slug) == before


def rewrite(net, hid, change):
    row = net.store.one('SELECT * FROM resplit_history WHERE id=?', hid)
    snapshot = state.decode(row['before_state'], row['before_digest'])
    change(snapshot)
    payload, digest = state.encode(snapshot)
    with net.store.tx() as db:
        db.execute('UPDATE resplit_history SET before_state=?,before_digest=? WHERE id=?', (payload, digest, hid))


def test_snapshot_is_scoped_to_project_and_saved_function(saved):
    net, slug, hid, fid, _text = saved
    other = net.import_rom(make_rom(code={0: b'\xc9'}), name='other.sms', confirmed=True, log=lambda *_: None)
    for selected_slug, selected_fid, item in ((other, fid, None), (slug, 999999, None), (slug, fid, 'attempt:999999')):
        with pytest.raises(NetworkError, match='unavailable'):
            archive.read(net, selected_slug, hid, function_id=selected_fid, item=item)
    with pytest.raises(NetworkError, match='outside'):
        archive.read(net, slug, hid, offset=99999)
    with pytest.raises(NetworkError, match='outside'):
        archive.read(net, slug, hid, function_id=fid, item='best', start=999999)
    rewrite(net, hid, lambda snapshot: snapshot['project'].update(id=999999))
    with pytest.raises(NetworkError, match='different project'):
        archive.read(net, slug, hid)


@pytest.mark.parametrize('damage', ['compression', 'digest', 'rows', 'schema'])
def test_invalid_or_over_budget_snapshots_fail_without_live_changes(saved, damage, monkeypatch):
    net, slug, hid, fid, _text = saved
    before = capture(net, slug)
    if damage == 'compression':
        with net.store.tx() as db:
            db.execute('UPDATE resplit_history SET before_state=? WHERE id=?', (b'not compressed', hid))
    elif damage == 'digest':
        with net.store.tx() as db:
            db.execute('UPDATE resplit_history SET before_digest=? WHERE id=?', ('0' * 64, hid))
    elif damage == 'rows':
        monkeypatch.setattr(state, 'MAX_ROWS', 5)
    else:
        rewrite(net, hid, lambda snapshot: next(row for row in snapshot['tables']['functions'] if row['id'] == fid).pop('target'))
    with pytest.raises(NetworkError, match='invalid|budget|malformed'):
        archive.read(net, slug, hid, function_id=fid)
    monkeypatch.undo()
    assert capture(net, slug) == before


def test_old_identity_and_undone_snapshots_remain_inspectable(saved):
    net, slug, hid, fid, text = saved
    def legacy(snapshot):
        cfg = json.loads(snapshot['project']['config'])
        cfg['rom'].pop('identity', None)
        cfg['sms_profile'] = None
        snapshot['project']['config'] = json.dumps(cfg)
    rewrite(net, hid, legacy)
    with net.store.tx() as db:
        db.execute('UPDATE resplit_history SET undone_at=1 WHERE id=?', (hid,))
    result = archive.read(net, slug, hid, function_id=fid, item='best', limit=archive.MAX_CHARS)
    assert result['text'] == text and result['origin']['sha1'] and result['origin']['undone_at'] == 1
    assert result['origin']['normalized']['sha256'] is None


def test_large_metadata_is_disclosed_as_clipped_while_complete_text_remains_available(saved):
    net, slug, hid, fid, _text = saved
    def large(snapshot):
        row = next(row for row in snapshot['tables']['functions'] if row['id'] == fid)
        row['name'] = 'authored_name_' * 100
        snapshot['tables']['attempts'][0]['model'] = 'authored_model_' * 100
    rewrite(net, hid, large)
    selected = archive.read(net, slug, hid, function_id=fid)
    assert len(selected['function']['name']) == 512 and selected['function']['fields_truncated'] == ['name']
    attempt = next(item for item in selected['items'] if item['key'].startswith('attempt:'))
    assert len(attempt['provenance']['model']) == 512
    assert attempt['provenance']['fields_truncated'] == ['model']
    complete = archive.read(net, slug, hid, function_id=fid, item='provenance')
    full = json.loads(complete['text'])
    assert full['function']['name'] == 'authored_name_' * 100
    assert full['attempts'][0]['model'] == 'authored_model_' * 100
    assert 'target' not in full['function'] and 'source' not in full['attempts'][0]


def test_current_input_can_be_unavailable_without_losing_access_to_saved_text(saved):
    from pathlib import Path

    net, slug, hid, fid, text = saved
    proj = net.project_row(slug)
    (Path(proj['root']) / net.cfg(proj)['rom']['file']).unlink()
    result = archive.read(net, slug, hid, function_id=fid, item='best', limit=archive.MAX_CHARS)
    assert result['text'] == text and result['origin']['intent'] == 'annotated-original'
