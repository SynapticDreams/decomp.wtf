"""Private SMS/GG resplit recovery preserves work and refuses stale or conflicting undo."""
import json
import sqlite3
import time
from pathlib import Path

import pytest

from decompnet.app import banked_resplit_history as history, banked_resplit_state as state
from decompnet.app.engine import RomNetwork
from decompnet.network import NetworkError
from decompnet.rom import sms, sms_asm
from decompnet.store import Store

from .test_sms import make_rom

SOURCE = ('; Returns without changing registers and retains the following declared byte.\n'
          '; Input: none. Output: caller registers and flags are preserved.\n'
          'RetainedReturn:\n    ret\n    .db $00\n')


@pytest.fixture(params=[('sms', 4), ('gg', 6)], ids=['sms', 'gg'])
def project(tmp_path, request):
    platform, region = request.param
    net = RomNetwork(tmp_path / 'state.db', tmp_path / 'projects')
    net.auto_install_tools = False
    image = make_rom(region=region, code={0: bytes.fromhex('cd0002 18fe'), 0x200: b'\xc9'})
    slug = net.import_rom(image, name=f'fixture.{platform}', confirmed=True, log=lambda *_: None)
    net.sms.configure(slug, 'sega', 'annotated-original', 'The authored fixture specifies its cartridge selector wiring.')
    proj = net.project_row(slug)
    return net, slug, proj


def snapshot(net, slug):
    return history.capture(net, net.project_row(slug))


def table(net, name, pid):
    return [dict(r) for r in net.store.all(f'SELECT * FROM {name} WHERE project_id=? ORDER BY rowid', pid)]


@pytest.mark.skipif(not sms_asm.available(), reason='needs WLA-DX')
def test_changed_documented_source_and_attempts_are_recoverable_and_rebuild_after_undo(project):
    net, slug, proj = project
    fn = net.store.one('SELECT * FROM functions WHERE project_id=? AND rom_offset=512', proj['id'])
    agent, _ = net.local_agent('fixture_writer')
    with net.store.tx() as db:
        db.execute("UPDATE functions SET target=?,size=2,status='asm' WHERE id=?", (b'\xc9\0', fn['id']))
        db.execute("INSERT INTO corrections(project_id,kind,rom_offset,cpu,count,reason) VALUES(?,'data',513,513,1,?)",
                   (proj['id'], 'The fixture declares the byte after the return as data.'))
        db.execute("INSERT OR REPLACE INTO data_regions(project_id,rom_offset,size,kind,why) VALUES(?,513,1,'data',?)",
                   (proj['id'], 'The older fixture map includes the declared trailing byte.'))
    result = net.document_function(agent, slug, fn['name'], SOURCE)
    assert result.startswith('✅ DOCUMENTED:'), result
    old = net.store.one('SELECT * FROM functions WHERE id=?', fn['id'])
    before = snapshot(net, slug)
    preview = net.resplit_banked(slug, log=lambda *_: None)
    assert preview['removed'] >= 1 and not net.resplit_history(slug)['history']
    detail = next(item for item in preview['changed_work'] if item['id'] == old['id'])
    assert detail['accepted_source'] and detail['requires_revalidation'] and detail['action'] == 'archived'
    assert detail['overlap_count'] == 1 and detail['overlaps'][0]['size'] == 1
    result = net.resplit_banked(slug, apply=True, log=lambda *_: None)
    fresh = net.store.one('SELECT * FROM functions WHERE project_id=? AND rom_offset=512', proj['id'])
    assert fresh['id'] != old['id']
    assert not net.store.one('SELECT 1 FROM attempts WHERE function_id=?', fresh['id'])
    listing = net.resplit_history(slug)['history'][0]
    assert listing['summary']['archived_documented'] == listing['summary']['archived_attempts'] == 1
    assert 'before_state' not in listing and old['matched_source'] not in json.dumps(listing)
    saved = net.store.one('SELECT * FROM resplit_history WHERE id=?', result['history_id'])
    retained = state.decode(saved['before_state'], saved['before_digest'])
    assert next(r for r in retained['tables']['functions'] if r['id'] == old['id']) == dict(old)
    assert retained['tables']['attempts'] == before['tables']['attempts']
    assert net.undo_resplit(slug, result['history_id']) == {'undone': result['history_id']}
    assert snapshot(net, slug) == before
    export = net.export_rom(slug, log=lambda *_: None)
    assert export['identical'] and export['documented'] == 1 and not export['left_out']
    generated = (Path(export['path']) / 'build' / 'disassembly' / 'bank_000.asm').read_text()
    assert '; documented in assembly: documented/RetainedReturn.asm' in generated
    assert old['matched_source'].strip() in generated
    cfg = net.cfg(net.project_row(slug))
    image = (Path(proj['root']) / cfg['rom']['file']).read_bytes()
    assert (Path(export['path']) / 'build' / f"game.{cfg['platform']}").read_bytes() == image


def test_unchanged_claim_notes_review_and_attempts_survive_apply_and_undo(project):
    net, slug, proj = project
    fn = net.store.one('SELECT * FROM functions WHERE project_id=? AND rom_offset=512', proj['id'])
    agent, _ = net.local_agent('fixture_reader')
    with net.store.tx() as db:
        db.execute('UPDATE functions SET meta=?,best_source=?,attempts=1 WHERE id=?',
                   (json.dumps({'sample': True, 'review': 'retain this review'}), 'prior fixture attempt', fn['id']))
        db.execute('INSERT INTO claims VALUES(?,?,?,?)', (fn['id'], agent.id, time.time(), time.time() + 300))
        db.execute('INSERT INTO attempts(function_id,agent_id,score,source) VALUES(?,?,?,?)',
                   (fn['id'], agent.id, 3, 'prior fixture attempt'))
        db.execute('INSERT INTO notes(project_id,function_id,text) VALUES(?,?,?)', (proj['id'], fn['id'], 'Keep this evidence.'))
    before = snapshot(net, slug)
    result = net.resplit_banked(slug, apply=True, log=lambda *_: None)
    for name in ('attempts', 'claims', 'notes'):
        assert snapshot(net, slug)['tables'][name] == before['tables'][name]
    fn_after = net.store.one('SELECT * FROM functions WHERE id=?', fn['id'])
    assert json.loads(fn_after['meta'])['sample'] and fn_after['best_source'] == 'prior fixture attempt'
    net.undo_resplit(slug, result['history_id'])
    assert snapshot(net, slug) == before


@pytest.mark.parametrize('change', ['note', 'symbol', 'correction', 'claim', 'context', 'sidecar'])
def test_new_work_or_input_prevents_undo_without_losing_either_state(project, change):
    net, slug, proj = project
    result = net.resplit_banked(slug, apply=True, log=lambda *_: None)
    fn = net.store.one('SELECT * FROM functions WHERE project_id=? LIMIT 1', proj['id'])
    if change == 'sidecar':
        cfg = net.cfg(proj)
        (Path(proj['root']) / cfg['rom']['file']).with_suffix('.sym').write_text('00:0200 NewEvidence\n')
    else:
        with net.store.tx() as db:
            sql, args = {
                'note': ('INSERT INTO notes(project_id,text) VALUES(?,?)', (proj['id'], 'new evidence')),
                'symbol': ("INSERT INTO symbols(project_id,name,address) VALUES(?,'NewEvidence',512)", (proj['id'],)),
                'correction': ("INSERT INTO corrections(project_id,kind,rom_offset) VALUES(?,'data',513)", (proj['id'],)),
                'claim': ('INSERT INTO claims VALUES(?,?,?,?)', (fn['id'], 1, 0, time.time() + 300)),
                'context': ('UPDATE context_versions SET header=? WHERE project_id=?', ('changed header', proj['id'])),
            }[change]
            db.execute(sql, args)
    before = snapshot(net, slug)
    with pytest.raises(NetworkError, match='newer work'):
        net.undo_resplit(slug, result['history_id'])
    assert snapshot(net, slug) == before
    assert net.resplit_history(slug)['history'][0]['undone_at'] is None


def test_concurrent_work_added_during_discovery_refuses_apply(project, monkeypatch):
    net, slug, proj = project
    original, functions = sms.split, table(net, 'functions', proj['id'])

    def split(*args, **kwargs):
        result = original(*args, **kwargs)
        with net.store.tx() as db:
            db.execute('INSERT INTO notes(project_id,text) VALUES(?,?)', (proj['id'], 'Concurrent evidence'))
        return result

    monkeypatch.setattr(sms, 'split', split)
    with pytest.raises(NetworkError, match='changed during resplit'):
        net.resplit_banked(slug, apply=True, log=lambda *_: None)
    assert table(net, 'functions', proj['id']) == functions
    assert net.store.one("SELECT 1 FROM notes WHERE text='Concurrent evidence'")
    assert not net.resplit_history(slug)['history']


def test_stale_preview_cannot_apply_after_new_work_or_changed_discovery(project, monkeypatch):
    net, slug, proj = project
    preview = net.resplit_banked(slug, log=lambda *_: None)
    with net.store.tx() as db:
        db.execute("INSERT INTO notes(project_id,text) VALUES(?,'Added after preview')", (proj['id'],))
    before = snapshot(net, slug)
    with pytest.raises(NetworkError, match='preview is stale'):
        net.resplit_banked(slug, apply=True, expected_plan=preview['plan'], log=lambda *_: None)
    assert snapshot(net, slug) == before and not net.resplit_history(slug)['history']
    preview = net.resplit_banked(slug, log=lambda *_: None)
    original = sms.split

    def changed_split(*args, **kwargs):
        return [fn for fn in original(*args, **kwargs) if fn.rom != 512]

    monkeypatch.setattr(sms, 'split', changed_split)
    with pytest.raises(NetworkError, match='preview is stale'):
        net.resplit_banked(slug, apply=True, expected_plan=preview['plan'], log=lambda *_: None)
    assert snapshot(net, slug) == before


def test_sidecar_change_during_database_updates_rolls_back_work_and_keeps_the_external_edit(project, monkeypatch):
    net, slug, proj = project
    before, original = snapshot(net, slug), history.mark_sms
    path = (Path(proj['root']) / net.cfg(proj)['rom']['file']).with_suffix('.sym')

    def mark(db, pid):
        original(db, pid)
        path.write_text('00:0200 NewEvidence\n')

    monkeypatch.setattr(history, 'mark_sms', mark)
    with pytest.raises(NetworkError, match='inputs changed during resplit'):
        net.resplit_banked(slug, apply=True, log=lambda *_: None)
    after = snapshot(net, slug)
    assert after['tables'] == before['tables'] and after['project'] == before['project']
    assert path.read_text() == '00:0200 NewEvidence\n' and not net.resplit_history(slug)['history']


def test_classification_failure_rolls_back_all_updates_and_history(project, monkeypatch):
    net, slug, proj = project
    before = snapshot(net, slug)
    original = history.mark_sms

    def fail(db, pid):
        original(db, pid)
        db.execute("INSERT INTO notes(project_id,text) VALUES(?,'Uncommitted mutation')", (pid,))
        raise RuntimeError('fixture classification failure')

    monkeypatch.setattr(history, 'mark_sms', fail)
    with pytest.raises(RuntimeError, match='classification failure'):
        net.resplit_banked(slug, apply=True, log=lambda *_: None)
    assert snapshot(net, slug) == before and not net.resplit_history(slug)['history']


def test_commit_failure_rolls_back_the_apply_and_leaves_the_connection_usable(project):
    net, slug, _proj = project
    before = snapshot(net, slug)
    net.store.conn.executescript('''
        CREATE TABLE guard_parent(id INTEGER PRIMARY KEY);
        CREATE TABLE guard_child(parent_id INTEGER REFERENCES guard_parent(id) DEFERRABLE INITIALLY DEFERRED);
        CREATE TRIGGER fail_history_commit AFTER INSERT ON resplit_history BEGIN
            INSERT INTO guard_child(parent_id) VALUES(7);
        END;
    ''')
    with pytest.raises(sqlite3.IntegrityError, match='FOREIGN KEY'):
        net.resplit_banked(slug, apply=True, log=lambda *_: None)
    assert not net.store.conn.in_transaction
    assert snapshot(net, slug) == before and not net.resplit_history(slug)['history']
    with net.store.tx() as db:
        db.execute('DROP TRIGGER fail_history_commit')
    assert net.resplit_banked(slug, apply=True, log=lambda *_: None)['history_id']


def test_repeated_resplits_undo_in_order_and_delete_their_private_history_with_project(project):
    net, slug, proj = project
    before = snapshot(net, slug)
    first = net.resplit_banked(slug, apply=True, log=lambda *_: None)['history_id']
    second = net.resplit_banked(slug, apply=True, log=lambda *_: None)['history_id']
    with pytest.raises(NetworkError, match='latest'):
        net.undo_resplit(slug, first)
    net.undo_resplit(slug, second)
    net.undo_resplit(slug, first)
    assert snapshot(net, slug) == before
    net.remove_project(slug)
    assert not net.store.one('SELECT 1 FROM resplit_history WHERE project_id=?', proj['id'])


@pytest.mark.parametrize('collision', ['functions', 'attempts'])
def test_reused_ids_in_another_project_are_never_overwritten_by_undo(project, collision):
    net, slug, proj = project
    with net.store.tx() as db:
        old_id = db.execute("INSERT INTO functions(project_id,name,rom_offset,vram,size,target) VALUES(?,'OldPiece',768,768,1,?)",
                            (proj['id'], b'\0')).lastrowid
        attempt_id = db.execute("INSERT INTO attempts(function_id,source) VALUES(?,'Old attempt')", (old_id,)).lastrowid
    result = net.resplit_banked(slug, apply=True, log=lambda *_: None)
    assert not net.store.one('SELECT 1 FROM functions WHERE id=?', old_id)
    with net.store.tx() as db:
        other = db.execute("INSERT INTO projects(slug,root,config) VALUES('other','project','{}')").lastrowid
        foreign_id = old_id if collision == 'functions' else 1_000_000
        db.execute("INSERT INTO functions(id,project_id,name,target) VALUES(?,?,'OtherWork',?)", (foreign_id, other, b'\xc9'))
        if collision == 'attempts':
            db.execute("INSERT INTO attempts(id,function_id,source) VALUES(?,?,'Other attempt')", (attempt_id, foreign_id))
    before = snapshot(net, slug)
    with pytest.raises(NetworkError, match='outside this project'):
        net.undo_resplit(slug, result['history_id'])
    assert snapshot(net, slug) == before
    assert net.store.one('SELECT name FROM functions WHERE id=?', foreign_id)['name'] == 'OtherWork'


@pytest.mark.parametrize('related', ['attempts', 'claims', 'notes', 'twin_misses'])
def test_undo_never_attaches_new_unowned_records_to_restored_function_ids(project, related):
    net, slug, proj = project
    with net.store.tx() as db:
        old_id = db.execute("INSERT INTO functions(project_id,name,rom_offset,vram,size,target) VALUES(?,'OldPiece',768,768,1,?)",
                            (proj['id'], b'\0')).lastrowid
    result = net.resplit_banked(slug, apply=True, log=lambda *_: None)
    assert not net.store.one('SELECT 1 FROM functions WHERE id=?', old_id)
    with net.store.tx() as db:
        sql = {
            'attempts': "INSERT INTO attempts(function_id,source) VALUES(?,'Unowned source')",
            'claims': 'INSERT INTO claims(function_id,agent_id) VALUES(?,1)',
            'notes': "INSERT INTO notes(function_id,text) VALUES(?,'Unowned note')",
            'twin_misses': "INSERT INTO twin_misses(function_id,source_hash) VALUES(?,'fixture')",
        }[related]
        db.execute(sql, (old_id,))
    before = snapshot(net, slug)
    with pytest.raises(NetworkError, match='outside this project'):
        net.undo_resplit(slug, result['history_id'])
    assert snapshot(net, slug) == before
    assert not net.store.one('SELECT 1 FROM functions WHERE id=?', old_id)


@pytest.mark.parametrize('limit,value', [('MAX_ROWS', 1), ('MAX_BYTES', 100)])
def test_snapshot_budgets_fail_before_discovery_or_mutation(project, monkeypatch, limit, value):
    net, slug, _proj = project
    before = snapshot(net, slug)
    calls = []
    with monkeypatch.context() as limited:
        limited.setattr(state, limit, value)
        limited.setattr(sms, 'split', lambda *_a, **_k: calls.append(True) or [])
        with pytest.raises(NetworkError, match='budget'):
            net.resplit_banked(slug, apply=True, log=lambda *_: None)
    assert not calls and snapshot(net, slug) == before and not net.resplit_history(slug)['history']


def test_claim_on_a_changed_target_blocks_apply_while_unchanged_claims_are_retained(project):
    net, slug, proj = project
    fn = net.store.one('SELECT * FROM functions WHERE project_id=? AND rom_offset=512', proj['id'])
    agent, _ = net.local_agent('active_reader')
    with net.store.tx() as db:
        db.execute('UPDATE functions SET target=?,size=2 WHERE id=?', (b'\xc9\0', fn['id']))
        db.execute('INSERT INTO claims VALUES(?,?,?,?)', (fn['id'], agent.id, time.time(), time.time() + 300))
    before = snapshot(net, slug)
    with pytest.raises(NetworkError, match='release claims on changed functions'):
        net.resplit_banked(slug, apply=True, log=lambda *_: None)
    assert snapshot(net, slug) == before and not net.resplit_history(slug)['history']


def test_background_analysis_blocks_apply_and_undo_without_mutation(project):
    net, slug, _proj = project
    result = net.resplit_banked(slug, apply=True, log=lambda *_: None)
    before = snapshot(net, slug)
    net.autopilots[slug] = {'state': 'running'}
    for operation in (lambda: net.resplit_banked(slug, apply=True, log=lambda *_: None),
                      lambda: net.undo_resplit(slug, result['history_id'])):
        with pytest.raises(NetworkError, match='background analysis'):
            operation()
    assert snapshot(net, slug) == before
    net.autopilots.pop(slug)


def test_history_pagination_is_project_scoped_and_keeps_latest_active_visible(project):
    net, slug, proj = project
    with net.store.tx() as db:
        for number in range(53):
            db.execute('INSERT INTO resplit_history(project_id,created_at,before_state,before_digest,after_digest,summary) '
                       'VALUES(?,0,?,?,?,?)', (proj['id'], b'', '0' * 64, '0' * 64, json.dumps({'removed': number})))
    page = net.resplit_history(slug)
    assert len(page['history']) == 50 and page['truncated'] and page['latest_active_id'] == page['history'][0]['id']
    older = net.resplit_history(slug, page['next_before'])
    assert len(older['history']) == 3 and not older['truncated'] and older['next_before'] is None
    assert older['latest_active_id'] == page['latest_active_id']


def test_changed_work_preview_discloses_truncation_without_source():
    from decompnet.app.banked_resplit_changes import describe
    before = {'tables': {'functions': [dict(id=n, name=f'Entry{n}', rom_offset=n, vram=n, size=1,
                                           status='documented', matched_source='private fixture text') for n in range(130)],
                          'attempts': [], 'claims': [], 'notes': []}}
    report = describe(before, [], set())
    assert report['changed_work_count'] == 130 and len(report['changed_work']) == 100 and report['changed_work_truncated']
    assert 'private fixture text' not in json.dumps(report)


def test_old_database_gains_history_idempotently_and_snapshot_decode_is_bounded(tmp_path, monkeypatch):
    path = tmp_path / 'old.db'
    store = Store(path)
    store.conn.execute("INSERT INTO projects(id,slug,root,config) VALUES(1,'fixture','project','{}')")
    store.conn.execute("INSERT INTO functions(project_id,name,target,matched_source) VALUES(1,'Retained',?,?)",
                       (b'\xc9', 'fixture retained source'))
    store.conn.execute('DROP TABLE resplit_history')
    store.conn.close()
    for _ in range(2):
        store = Store(path)
        assert store.conn.execute('SELECT COUNT(*) FROM resplit_history').fetchone()[0] == 0
        assert store.conn.execute('SELECT target,matched_source FROM functions').fetchone()['target'] == b'\xc9'
        store.conn.close()
    payload, digest = state.encode({'version': 1, 'tables': {key: [] for key in state.TABLES}, 'text': b'\0' * 1024})
    assert state.decode(payload, digest)['text'] == b'\0' * 1024
    for invalid in (payload + b'extra', b'not compressed'):
        with pytest.raises(NetworkError, match='invalid'):
            state.decode(invalid, digest)
    with pytest.raises(NetworkError, match='invalid'):
        state.decode(payload, '0' * 64)
    monkeypatch.setattr(state, 'MAX_BYTES', 100)
    with pytest.raises(NetworkError, match='decode budget'):
        state.decode(payload, digest)
    with pytest.raises(NetworkError, match='work budget'):
        state.encode({'too_large': 'x' * 1000})
