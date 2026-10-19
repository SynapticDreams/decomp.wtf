"""Authored assembly work: check receipts, claim-safe deferral and evidence-bound retries."""
import json
from types import SimpleNamespace

import pytest
from starlette.testclient import TestClient

from decompnet.app import agents, tools
from decompnet.app.engine import RomNetwork
from decompnet.app.server import build
from decompnet.network import NetworkError
from decompnet.rom import gb_asm


@pytest.fixture
def work(tmp_path, monkeypatch):
    net = RomNetwork(tmp_path / 'app.db', tmp_path)
    cfg = {'kind': 'rom', 'platform': 'gbc', 'arch': 'sm83',
           'rom': {'size': 0x8000, 'mbc': 'MBC1', 'file': 'authored.gbc'}, 'compiler': {'toolchain': 'gbdk-2020', 'flags': []}}
    (tmp_path / 'authored.gbc').write_bytes(bytes(0x8000))
    with net.store.tx() as db:
        pid = db.execute('INSERT INTO projects(slug,name,arch,root,config) VALUES(?,?,?,?,?)',
                         ('authored', 'Authored fixture', 'sm83', str(tmp_path), json.dumps(cfg))).lastrowid
        db.execute('INSERT INTO context_versions(project_id,version,header) VALUES(?,?,?)', (pid, 1, ''))
        for name, offset in [('First', 0x100), ('Second', 0x110)]:
            db.execute('INSERT INTO functions(project_id,name,size,n_insns,target,asm,relocs,unit,vram,rom_offset,status,meta) '
                       'VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
                       (pid, name, 1, 1, b'\xc9', 'ret', '[]', 'bank000', offset, offset, 'asm',
                        json.dumps({'asm_code': 'hand-written routine'})))
    verdict = gb_asm.Verdict(False, 1, 1, ['3. ROM target unresolved; keep the reference pending'])
    judge = SimpleNamespace(available=lambda: True, judge=lambda *args: verdict, draft=lambda r: r.name + ': ret', AsmError=gb_asm.AsmError)
    monkeypatch.setattr(net, '_asm_judge', lambda proj: judge)
    agent = net.authenticate(net.register_agent('writer'))
    return net, agent, verdict


def test_mapping_blocker_preserves_source_and_stops_automatic_reclaims(work):
    net, agent, _ = work
    assert net.document_function(agent, 'authored', 'First', '; authored\nFirst: ret').startswith('❌')
    row = net._function('First', 'authored')
    assert row['status'] == 'asm' and row['best_source'] == '; authored\nFirst: ret'
    view = net.assembly.view(net._project('authored'), row)
    assert view['deferred'] and view['validation']['byte_identical']
    assert [c['state'] for c in view['validation']['checks']] == ['passed', 'passed', 'pending', 'passed', 'passed', 'passed']
    assert not net.store.one('SELECT 1 FROM claims')
    assert agents.Manager._asm_left(net, net._project('authored')) == 1
    assert net.function_map('authored')[0]['deferred']
    net.claim_asm_row(agent, 'authored')
    assert net.store.one('SELECT name FROM functions JOIN claims ON functions.id=claims.function_id')['name'] == 'Second'
    net.release(agent, 'Second', 'Authored release notes', 'authored')
    with pytest.raises(NetworkError, match='deferred'):
        net.claim_asm_row(agent, 'authored', 'First')
    with pytest.raises(NetworkError, match='deferred'):
        net.document_function(agent, 'authored', 'First', 'First: ret')


@pytest.mark.parametrize('problem', ['2. use a project name', '3. target names the wrong bank', '4. instructions must stay instructions'])
def test_source_errors_are_not_automatically_deferred(work, problem):
    net, agent, verdict = work
    verdict.problems = [problem]
    net.document_function(agent, 'authored', 'First', 'First: ret')
    assert not net.assembly.view(net._project('authored'), net._function('First', 'authored'))['deferred']


@pytest.mark.parametrize('change', ['symbol', 'layout', 'profile', 'target', 'validator'])
def test_changed_judge_inputs_reenable_deferred_work_and_mark_old_checks_stale(work, monkeypatch, change):
    net, agent, _ = work
    net.document_function(agent, 'authored', 'First', 'First: ret')
    with net.store.tx() as db:
        if change == 'symbol':
            db.execute('INSERT INTO symbols(project_id,name,address) VALUES(?,?,?)', (1, 'NewEvidence', 0x120))
        elif change == 'layout':
            db.execute("UPDATE functions SET vram=0x111 WHERE name='Second'")
        elif change == 'profile':
            cfg = net.cfg(net._project('authored')); cfg['sms_profile'] = {'reason': 'new authored mapping evidence'}
            db.execute('UPDATE projects SET config=?', (json.dumps(cfg),))
        elif change == 'target':
            db.execute("UPDATE functions SET target=? WHERE name='First'", (b'\x00',))
        else:
            monkeypatch.setattr('decompnet.app.assembly_work.revision', lambda arch: 'new validator')
    view = net.assembly.view(net._project('authored'), net._function('First', 'authored'))
    assert not view['deferred'] and view['evidence_changed'] and not view['validation']['current']
    assert net.assembly.eligible(net._project('authored'), net._function('First', 'authored'))


def test_manual_defer_tool_releases_own_claim_and_operator_can_resume(work):
    net, agent, _ = work
    net.claim_asm_row(agent, 'authored', 'First')
    out = tools.call(net, agent, 'authored', 'defer_documentation',
                     {'function': 'First', 'reason': 'Needs an authored entry correction reviewed'})
    assert json.loads(out)['deferred']
    assert not net.store.one('SELECT 1 FROM claims')
    assert net.assembly.change('authored', 'First', resume=True)['deferred'] is False
    assert net.assembly.eligible(net._project('authored'), net._function('First', 'authored'))


def test_defer_cannot_take_another_helpers_claim_or_mutate_c_work(work):
    net, agent, _ = work
    net.claim_asm_row(agent, 'authored', 'First')
    with pytest.raises(NetworkError, match='being worked on'):
        net.assembly.change('authored', 'First', reason='Needs an authored boundary repair')
    other = net.authenticate(net.register_agent('other'))
    with pytest.raises(NetworkError, match='being worked on'):
        net.assembly.change('authored', 'First', reason='Needs an authored boundary repair', agent=other)
    with pytest.raises(NetworkError, match='claim the assembly'):
        net.assembly.change('authored', 'Second', reason='Needs an authored boundary repair', agent=other)
    with net.store.tx() as db:
        db.execute("UPDATE functions SET status='open' WHERE name='Second'")
    with pytest.raises(NetworkError, match='only hand-written'):
        net.assembly.change('authored', 'Second', reason='Needs an authored boundary repair')


def test_receipt_does_not_claim_unreached_checks_passed(work):
    net, _, verdict = work
    verdict.same = verdict.size = 0
    verdict.problems = ['6. conflicting name prevents assembly']
    proj, fn = net._project('authored'), net._function('First', 'authored')
    receipt = net.assembly.receipt(proj, fn, net._routine(proj, fn), 'First: ret', verdict)
    assert receipt['checks'][0]['state'] == 'failed'
    assert receipt['checks'][1]['state'] == 'not_checked'
    assert receipt['checks'][5]['state'] == 'failed'


def test_success_keeps_checks_without_semantic_approval(work):
    net, agent, verdict = work
    verdict.ok = True; verdict.problems = []; verdict.text = 'First: ret'; verdict.label = 'First'
    assert net.document_function(agent, 'authored', 'First', verdict.text).startswith('✅')
    row = net._function('First', 'authored')
    assert row['status'] == 'documented'
    view = net.assembly.view(net._project('authored'), row)
    assert not view['deferred'] and all(c['state'] == 'passed' for c in view['validation']['checks'])
    assert 'approved' not in view


def test_pinned_assembly_has_the_right_prompt_claim_and_stop_conditions(work, tmp_path, monkeypatch):
    net, agent, _ = work
    mcp, manager, security = build(net, tmp_path / '.decomp', 6497, 'fixture-secret')
    monkeypatch.setattr(agents.Manager, '_run', lambda self, session: None)
    client = TestClient(mcp.streamable_http_app(transport_security=security, host='127.0.0.1'),
                        base_url='http://127.0.0.1:6497')
    body = {'kind': 'claude', 'slug': 'authored', 'options': {'track': 'asm', 'pin': 'First', 'polish': True}}
    assert client.post('/api/agents/start', json=body, headers={'X-Decomp': '1'}).status_code == 401
    client.cookies.set('decomp_live', 'fixture-secret')
    response = client.post('/api/agents/start', json=body, headers={'X-Decomp': '1'})
    assert response.status_code == 200, response.text
    session = manager.sessions[response.json()['started'][0]]
    assert session.options['track'] == 'asm' and not session.options['polish'] and not session.options.get('lean')
    assert 'claim_function(track="asm")' in manager._prompt(session)
    assert 'Work only on First' in manager._prompt(session)
    assert manager._pin_check(session, 'First') == ''
    net.pinned[agent.id] = 'First'
    with pytest.raises(NetworkError, match='works on First only'):
        net.claim(agent, 'authored', 'Second', track='asm')
    assert net.claim(agent, 'authored', track='asm').startswith('## CLAIMED')
    assert net.store.one('SELECT name FROM functions JOIN claims ON functions.id=claims.function_id')['name'] == 'First'
    net.assembly.change('authored', 'First', reason='Authored mapping evidence needs review', agent=agent)
    assert 'deferred' in manager._pin_check(session, 'First')
    assert client.post('/api/assembly/queue', json={'slug': 'authored', 'function': 'First', 'resume': True}).status_code == 403
    response = client.post('/api/assembly/queue', json={'slug': 'authored', 'function': 'First', 'resume': True},
                           headers={'X-Decomp': '1'})
    assert response.status_code == 200 and not response.json()['deferred']
    body['options']['lean'] = 'one'
    response = client.post('/api/agents/start', json=body, headers={'X-Decomp': '1'})
    assert response.status_code == 400 and 'C lean loop' in response.json()['error']


@pytest.mark.parametrize('platform', ['sms', 'gg'])
def test_sms_and_gg_blockers_are_bound_to_declared_mapping_and_visible_in_the_api(work, tmp_path, platform):
    net, agent, _ = work
    cfg = net.cfg(net._project('authored'))
    cfg.update(platform=platform, arch='z80')
    image = bytearray(0x8000); image[0x100] = image[0x110] = 0xC9
    (tmp_path / 'authored.gbc').write_bytes(image)
    with net.store.tx() as db:
        db.execute('UPDATE projects SET arch=?,config=?', ('z80', json.dumps(cfg)))
    net.sms.configure('authored', 'sega', 'annotated-original', 'The authored fixture declares Sega cartridge wiring.')
    net.document_function(agent, 'authored', 'First', '; authored\nFirst: ret')
    fn = net._function('First', 'authored')
    assert net.assembly.view(net._project('authored'), fn)['deferred']
    mcp, _, security = build(net, tmp_path / '.decomp', 6497, 'fixture-secret')
    client = TestClient(mcp.streamable_http_app(transport_security=security, host='127.0.0.1'),
                        base_url='http://127.0.0.1:6497')
    client.cookies.set('decomp_live', 'fixture-secret')
    detail = client.get('/api/function?slug=authored&name=First').json()
    assert detail['assembly_work']['deferred'] and detail['assembly_work']['validation']['current']
    response = client.get('/api/map?slug=authored').json()
    row = dict(zip(response['keys'], response['rows'][0]))
    assert row['deferred'] and row['assembly_bytes'] is True
    response = client.post('/api/assembly/queue', json={'slug': 'authored', 'function': 'First', 'resume': True},
                           headers={'X-Decomp': '1'})
    assert response.status_code == 200
    assert net.assembly.eligible(net._project('authored'), net._function('First', 'authored'))


def test_bounded_receipts_still_classify_failures_beyond_the_display_limit(work):
    net, _, verdict = work
    verdict.problems = ['2. authored name issue'] * 70 + ['5. hardware name missing']
    proj, fn = net._project('authored'), net._function('First', 'authored')
    receipt = net.assembly.receipt(proj, fn, net._routine(proj, fn), 'First: ret', verdict)
    assert receipt['truncated'] and receipt['checks'][1]['truncated']
    assert len(receipt['problems']) == 64 and len(receipt['checks'][1]['problems']) == 12
    assert receipt['checks'][4]['state'] == 'failed'


def test_operator_can_defer_their_own_manual_edit_but_not_a_helpers_claim(work):
    net, _, _ = work
    you, _ = net.local_agent('you')
    net.claim_asm_row(you, 'authored', 'First')
    assert net.assembly.change('authored', 'First', reason='Authored evidence needs manual repair')['deferred']
    assert not net.store.one('SELECT 1 FROM claims')
