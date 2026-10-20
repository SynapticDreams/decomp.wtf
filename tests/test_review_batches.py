"""Authored batch review/correction flows. All model responses are scripted; no paid helpers run."""
import json
import threading
import time

import pytest
from starlette.testclient import TestClient

from decompnet.app import agents, tools
from decompnet.app.server import build
from decompnet.app.assembly_work import digest
from decompnet.network import NetworkError
from .test_assembly_work import work  # noqa: F401
from .test_documentation_review import documented as documented_fixture, report, begin
from .test_sms_documented import game  # noqa: F401

REVIEWER = {'kind': 'claude', 'model': 'authored-reviewer'}
WRITER = {'kind': 'codex', 'model': 'authored-writer'}
FIXED = '; Returns immediately to the caller; no inputs.\nFirst: ret'


@pytest.fixture(name='documented')
def batch_documented(work):  # noqa: F811
    return documented_fixture.__wrapped__(work)


def comment_finding(documented):
    net, _, reviewer = documented
    inputs = begin(documented)
    net.documentation_review.submit(reviewer, 'authored', **report(inputs, verdict='needs_changes',
        followup='comments', concerns=['Clarify the return behavior without altering the instructions.']))
    net.documentation_review.active.pop(reviewer.id)


def writer(documented):
    net, _, _ = documented
    agent, _ = net.local_agent('comment-writer')
    net.documentation_review.begin(agent, 'authored', 'First', comments=True)
    inputs = json.loads(tools.call(net, agent, 'authored', 'get_documentation_review', {}))
    return agent, inputs


def propose(net, agent, inputs, source=FIXED):
    return tools.call(net, agent, 'authored', 'submit_comment_revision',
                      {'function':'First', 'review_context':inputs['review_context'], 'source':source})


def test_comment_candidate_is_validated_then_applied_only_after_independent_support(documented):
    net, _, _ = documented
    comment_finding(documented); agent, inputs = writer(documented)
    before = dict(net._function('First', 'authored'))
    assert propose(net, agent, inputs).startswith('Validated comment proposal')
    row = net._function('First', 'authored'); proposal = json.loads(row['meta'])['comment_revision']
    assert row['matched_source'] == before['matched_source'] and json.loads(row['meta'])['sample']
    with pytest.raises(NetworkError, match='different helper'):
        net.documentation_review.begin(agent, 'authored', 'First', candidate=proposal['token'])
    reviewer, _ = net.local_agent('independent-reader')
    net.documentation_review.begin(reviewer, 'authored', 'First', candidate=proposal['token'])
    candidate = json.loads(tools.call(net, reviewer, 'authored', 'get_documentation_review', {}))
    assert candidate['source'] == FIXED
    self_read = json.loads(tools.call(net, reviewer, 'authored', 'get_function', {'function':'First'}))
    assert self_read['documented_source'] == FIXED
    assert tools.call(net, reviewer, 'authored', 'submit_documentation_review', report(candidate)).startswith('AI review saved')
    row = net._function('First', 'authored'); meta = json.loads(row['meta'])
    assert row['status'] == 'documented' and row['matched_source'] == FIXED and meta['sample']
    assert row['target'] == before['target'] and meta['comment_history'][0]['source'] == before['matched_source']
    assert 'comment_revision' not in meta and meta['assembly_work']['validation']['source'] == digest(FIXED)
    receipt = net.function_detail('authored', 'First')['documentation_reviews'][0]
    assert receipt['applied'] and receipt['current']
    assert not net.store.one('SELECT 1 FROM claims')


@pytest.mark.parametrize('source', ['; changed\nFirst: nop', '; changed\nRenamed: ret', '; changed\n.DEFINE Thing 2\nFirst: ret',
    '; changed\nFirst: ret\n.db ";not a comment"', '; changed\nFirst: ret\nld a, 1'])
def test_writer_cannot_change_any_executable_content(documented, source):
    net, _, _ = documented
    comment_finding(documented); agent, inputs = writer(documented)
    assert 'comments only' in propose(net, agent, inputs, source)
    assert 'comment_revision' not in json.loads(net._function('First', 'authored')['meta'])
    assert 'read-only' in tools.call(net, agent, 'authored', 'compile_and_diff', {'function':'First','source':source})
    assert 'read-only' in tools.call(net, agent, 'authored', 'submit_documentation_review', report(inputs))


def test_comment_comparison_preserves_semicolons_in_strings_and_z80_registers(documented):
    net, _, _ = documented
    lines = net.documentation_review.code_lines
    assert lines("ex af, af' ; old\n.db 'a;b' ; old") == lines("; new\nex af, af' ; new\n.db 'a;b' ; new")
    assert lines('.db "a;b"') != lines('.db "a;c"')


def test_failed_validation_and_stop_keep_accepted_source_intact(documented, monkeypatch):
    net, _, _ = documented
    comment_finding(documented); agent, inputs = writer(documented)
    judge = net._asm_judge(net._project('authored'))
    verdict = judge.judge(None, None); verdict.ok = False; verdict.problems = ['3. missing mapping evidence']
    assert 'validation failed' in propose(net, agent, inputs)
    assert 'comment_revision' not in json.loads(net._function('First', 'authored')['meta'])
    verdict.ok = True; verdict.problems = []
    stop = threading.Event(); net.documentation_review.active[agent.id]['stop'] = stop
    original = judge.judge
    def stopped(*args):
        stop.set(); return original(*args)
    monkeypatch.setattr(judge, 'judge', stopped)
    assert 'stopped' in propose(net, agent, inputs)
    assert net._function('First', 'authored')['matched_source'] != FIXED


def wait_batch(manager):
    deadline = time.monotonic() + 8
    while manager.review_batches.active and time.monotonic() < deadline:
        time.sleep(.01)
    assert not manager.review_batches.active
    return manager.review_batches.view('authored')


def manager_for(documented, tmp_path, monkeypatch, verdict='supported', followup='none', candidate_verdict='supported'):
    net, _, _ = documented
    manager = agents.Manager(net, tmp_path / '.decomp', 'http://example.invalid/mcp')
    monkeypatch.setattr(manager, '_prepare', lambda slug: pytest.fail('batch must not start preparation/permuter'))
    calls = []
    def run(session, token, workdir):
        agent = net.authenticate(token); calls.append(session.options['track'])
        inputs = json.loads(tools.call(net, agent, 'authored', 'get_documentation_review', {}))
        if session.options['track'] == 'asm_comment_fix':
            result = propose(net, agent, inputs)
            assert result.startswith('Validated comment proposal'), result
        else:
            outcome = candidate_verdict if session.options.get('review_candidate') else verdict
            result = tools.call(net, agent, 'authored', 'submit_documentation_review', report(inputs,
                verdict=outcome, followup=('none' if outcome == 'supported' else 'evidence') if session.options.get('review_candidate') else followup,
                concerns=[] if outcome == 'supported' else ['Clarify the return behavior without guessing about its wider purpose.']))
            assert result.startswith('AI review saved'), result
        return True
    monkeypatch.setattr(manager, '_run_cli', run)
    return manager, calls


def test_batch_reviews_corrects_validates_and_rechecks_without_human_approval(documented, tmp_path, monkeypatch):
    net, _, _ = documented
    manager, calls = manager_for(documented, tmp_path, monkeypatch, 'needs_changes', 'comments')
    manager.review_batches.start('authored', REVIEWER, WRITER)
    batch = wait_batch(manager)
    assert calls == ['asm_review','asm_comment_fix','asm_review']
    assert batch['state'] == 'complete' and batch['counts']['corrected'] == 1 and batch['sessions'] == 3
    assert net._function('First', 'authored')['matched_source'] == FIXED
    assert net.function_detail('authored','First')['sample']
    assert all(s.options.get('review_batch') for s in manager.sessions.values())


@pytest.mark.parametrize('followup', ['evidence','layout'])
def test_uncertain_and_layout_reports_create_followups_without_writer_runs(documented, tmp_path, monkeypatch, followup):
    net, _, _ = documented
    manager, calls = manager_for(documented, tmp_path, monkeypatch, 'uncertain', followup)
    manager.review_batches.start('authored', REVIEWER, WRITER)
    batch = wait_batch(manager)
    assert calls == ['asm_review'] and batch['counts'][f'needs_{followup}'] == 1
    detail = net.function_detail('authored', 'First')
    assert detail['documentation_followup']['kind'] == followup and detail['documentation_followup']['current']
    assert detail['status'] == 'documented' and detail['source'] != FIXED and detail['sample']
    # Re-running a batch reuses this finding and never duplicates its note.
    manager.review_batches.start('authored', REVIEWER, WRITER); wait_batch(manager)
    assert calls == ['asm_review'] and net.store.one('SELECT COUNT(*) AS n FROM notes')['n'] == 1


def test_existing_uncertain_report_is_reused_without_manual_note_copying(documented, tmp_path, monkeypatch):
    net, _, reviewer = documented
    inputs = begin(documented)
    net.documentation_review.submit(reviewer, 'authored', **report(inputs, verdict='uncertain',
        concerns=['Trace the caller to establish the expected source pointer.']))
    net.documentation_review.active.pop(reviewer.id)
    manager, calls = manager_for(documented,tmp_path,monkeypatch)
    manager.review_batches.start('authored', REVIEWER, WRITER)
    batch = wait_batch(manager)
    assert not calls and batch['counts']['needs_evidence'] == 1
    assert 'source pointer' in net.function_detail('authored','First')['documentation_followup']['text']


def test_unsupported_candidate_keeps_original_source_and_saves_concerns(documented,tmp_path,monkeypatch):
    net, _, _ = documented
    before = net._function('First','authored')['matched_source']
    manager, calls = manager_for(documented,tmp_path,monkeypatch,'needs_changes','comments','uncertain')
    manager.review_batches.start('authored', REVIEWER, WRITER)
    batch = wait_batch(manager)
    assert len(calls) == 3 and batch['counts']['needs_evidence'] == 1
    assert net._function('First','authored')['matched_source'] == before
    receipt = net.function_detail('authored','First')['documentation_reviews'][0]
    assert receipt['candidate'] and not receipt.get('applied') and receipt['current']
    manager.review_batches.start('authored',REVIEWER,WRITER);wait_batch(manager)
    assert len(calls)==3 and net.store.one('SELECT COUNT(*) AS n FROM notes')['n']==1


def test_session_limit_pauses_then_resume_reuses_saved_work(documented,tmp_path,monkeypatch):
    net, _, _ = documented
    manager, calls = manager_for(documented,tmp_path,monkeypatch,'needs_changes','comments')
    manager.review_batches.start('authored', REVIEWER, WRITER, limits={'sessions':1})
    batch = wait_batch(manager)
    assert batch['state'] == 'paused' and calls == ['asm_review']
    manager.review_batches.start('authored', REVIEWER, WRITER, limits={'sessions':2},resume=True)
    batch = wait_batch(manager)
    assert calls == ['asm_review','asm_comment_fix','asm_review'] and batch['counts']['corrected'] == 1
    assert net._function('First','authored')['matched_source'] == FIXED


def test_stop_cancels_only_the_batch_helper_and_duplicate_batches_are_rejected(documented,tmp_path,monkeypatch):
    manager, _ = manager_for(documented,tmp_path,monkeypatch)
    entered = threading.Event()
    def waiting(session, token, workdir):
        entered.set(); session.stop.wait(5); return True
    monkeypatch.setattr(manager,'_run_cli',waiting)
    unrelated = agents.Session('unrelated','codex','Existing helper','authored','unrelated',{})
    manager.sessions[unrelated.id] = unrelated
    manager.review_batches.start('authored',REVIEWER,WRITER)
    assert entered.wait(5)
    with pytest.raises(NetworkError,match='already running'):
        manager.review_batches.start('authored',REVIEWER,WRITER)
    assert manager.running() == [{'kind':'codex','slug':'authored','options':{}}]
    manager.review_batches.stop('authored')
    batch = wait_batch(manager)
    assert batch['state'] == 'paused' and not unrelated.stop.is_set()


def test_batch_api_guards_limits_and_secrets(documented,tmp_path,monkeypatch):
    net, _, _ = documented
    mcp, manager, security = build(net,tmp_path/'.decomp',6497,'authored-secret')
    monkeypatch.setattr(agents,'_which',lambda cmd: '/authored/helper')
    monkeypatch.setattr(manager.review_batches,'run',lambda batch,control: None)
    client = TestClient(mcp.streamable_http_app(transport_security=security,host='127.0.0.1'),base_url='http://127.0.0.1:6497')
    body = {'slug':'authored','reviewer':{**REVIEWER,'api_key':'never-store-this'},'writer':WRITER,'fix_comments':True}
    assert client.post('/api/documented/batch',json=body).status_code == 401
    client.cookies.set('decomp_live','authored-secret')
    assert client.post('/api/documented/batch',json=body).status_code == 403
    for limits in ({'sessions':0},{'minutes':True},{'tokens':1},{'functions':501},{'token_limit':1000},True):
        assert client.post('/api/documented/batch',json={**body,'limits':limits},headers={'X-Decomp':'1'}).status_code == 400
    response = client.post('/api/documented/batch',json=body,headers={'X-Decomp':'1'})
    assert response.status_code == 200,response.text
    assert 'never-store-this' not in response.text
    stored = net.store.one("SELECT value FROM settings WHERE key LIKE 'review_batch:%'")['value']
    assert 'never-store-this' not in stored
    # A restarted app exposes saved progress as paused and does not launch helpers automatically.
    restored = agents.Manager(net,tmp_path/'.decomp','http://example.invalid/mcp')
    assert restored.review_batches.view('authored')['state'] == 'paused' and not restored.sessions


def test_production_batch_controls_pause_resume_correct_and_save_existing_findings(documented,tmp_path,monkeypatch):
    from .assembly_browser import live
    net, original_writer, _ = documented
    verdict = net._asm_judge(net._project('authored')).judge(None,None)
    verdict.label='Second'; verdict.text='; Authored second routine.\nSecond: ret'
    net.document_function(original_writer,'authored','Second',verdict.text)
    with net.store.tx() as db:
        fn=net._function('Second','authored'); meta=json.loads(fn['meta']); meta['sample']=True
        db.execute('UPDATE functions SET meta=? WHERE id=?',(json.dumps(meta),fn['id']))
    reader,_=net.local_agent('previous-reader')
    net.documentation_review.begin(reader,'authored','Second')
    inputs=json.loads(net.documentation_review.inputs(reader,'authored'))
    net.documentation_review.submit(reader,'authored',**report(inputs,function='Second',verdict='uncertain',
        concerns=['<img src=x> Trace the caller before assigning a higher-level purpose.']))
    net.documentation_review.active.pop(reader.id)
    def run(manager,session,token,workdir):
        agent=net.authenticate(token)
        inputs=json.loads(tools.call(net,agent,'authored','get_documentation_review',{}))
        if session.options['track']=='asm_comment_fix':
            result=propose(net,agent,inputs)
            assert result.startswith('Validated comment proposal'),result
        else:
            outcome='supported' if session.options.get('review_candidate') else 'needs_changes'
            result=tools.call(net,agent,'authored','submit_documentation_review',report(inputs,verdict=outcome,
                followup='none' if outcome=='supported' else 'comments',
                concerns=[] if outcome=='supported' else ['Clarify its return behavior, preserving all instructions.']))
            assert result.startswith('AI review saved'),result
        return True
    monkeypatch.setattr(agents.Manager,'_run_cli',run)
    monkeypatch.setattr(agents,'_which',lambda cmd: '/authored/helper')
    manager=live(net,tmp_path,monkeypatch,script_name='review_batch_live.js',run_helper=True)
    batch=wait_batch(manager)
    assert batch['counts']['corrected']==1 and batch['counts']['needs_evidence']==1


def test_real_sms_comment_revision_rebuilds_with_pinned_wla_dx(game):  # noqa: F811
    from decompnet.rom import sms_asm
    from .test_sms_documented import TEXT
    if not sms_asm.available():
        pytest.skip('needs WLA-DX')
    net, author = game
    assert net.document_function(author,'s','func_005_8a10',TEXT).startswith('✅ DOCUMENTED')
    fn=net._function('ClearMenuMap','s')
    reviewer,_=net.local_agent('authored-reader')
    net.documentation_review.begin(reviewer,'s',fn['name'])
    inputs=json.loads(net.documentation_review.inputs(reviewer,'s'))
    net.documentation_review.submit(reviewer,'s',**report(inputs,function=fn['name'],verdict='needs_changes',followup='comments',
        concerns=['Clarify this header while preserving the instructions.']))
    writer_agent,_=net.local_agent('authored-writer')
    net.documentation_review.begin(writer_agent,'s',fn['name'],comments=True)
    inputs=json.loads(net.documentation_review.inputs(writer_agent,'s'))
    result=net.documentation_review.propose_comments(writer_agent,'s',fn['name'],inputs['review_context'],
        '; Authored clarification of the existing description.\n'+fn['matched_source'])
    assert result.startswith('Validated comment proposal'),result
    proposal=json.loads(net._function(fn['name'],'s')['meta'])['comment_revision']
    assert proposal['validation']['byte_identical'] and all(c['state']=='passed' for c in proposal['validation']['checks'])
    assert net._function(fn['name'],'s')['matched_source']==fn['matched_source']


def test_reported_token_limit_pauses_before_another_helper_starts(documented,tmp_path,monkeypatch):
    manager,calls=manager_for(documented,tmp_path,monkeypatch,'needs_changes','comments')
    original=manager._run_cli
    def counted(session,token,workdir):
        result=original(session,token,workdir);session.tokens=2000;return result
    monkeypatch.setattr(manager,'_run_cli',counted)
    manager.review_batches.start('authored',REVIEWER,WRITER,limits={'tokens':1000})
    batch=wait_batch(manager)
    assert batch['state']=='paused' and 'token limit' in batch['reason'] and calls==['asm_review']


def test_time_limit_stops_an_active_batch_helper(documented,tmp_path,monkeypatch):
    manager,_=manager_for(documented,tmp_path,monkeypatch)
    entered=threading.Event()
    def blocked(session,token,workdir):
        entered.set();session.stop.wait(5);return True
    monkeypatch.setattr(manager,'_run_cli',blocked)
    manager.review_batches.start('authored',REVIEWER,WRITER,limits={'minutes':1})
    assert entered.wait(5)
    manager.review_batches.active['authored']['batch']['started_at']=time.time()-61
    batch=wait_batch(manager)
    assert batch['state']=='paused' and 'Time limit' in batch['reason']
    assert all(s.stop.is_set() for s in manager.sessions.values())


def test_completed_results_become_historical_and_resume_rechecks_them(documented,tmp_path,monkeypatch):
    net,_,_=documented
    manager,calls=manager_for(documented,tmp_path,monkeypatch)
    manager.review_batches.start('authored',REVIEWER,WRITER);batch=wait_batch(manager)
    assert batch['counts']['reviewed']==1
    # Current supported results cause a new batch to skip this routine without another model session.
    manager.review_batches.start('authored',REVIEWER,WRITER);empty=wait_batch(manager)
    assert empty['total']==0 and calls==['asm_review']
    manager.review_batches.save(batch)
    with net.store.tx() as db:
        db.execute("UPDATE functions SET matched_source=matched_source || '\n; newer authored explanation' WHERE name='First'")
    assert manager.review_batches.view('authored')['counts']['outdated']==1
    manager.review_batches.start('authored',REVIEWER,WRITER,resume=True);batch=wait_batch(manager)
    assert batch['counts']['outdated']==0 and calls==['asm_review','asm_review']


def test_restarted_manager_does_not_reuse_the_comment_authors_identity_for_review(documented,tmp_path,monkeypatch):
    net,_,_=documented
    author,_=net.local_agent('review-claude-1')
    with net.store.tx() as db:
        db.execute("UPDATE functions SET matched_agent_id=? WHERE name='First'",(author.id,))
    manager=agents.Manager(net,tmp_path/'.decomp','http://example.invalid/mcp')
    monkeypatch.setattr(manager,'_run',lambda session:None)
    sid,=manager.start('claude','authored',options={'pin':'First','track':'asm_review'})
    assert manager.sessions[sid].agent_name=='review-claude-2'


def test_changed_input_stops_the_old_batch_without_reusing_its_progress(documented,tmp_path,monkeypatch):
    net,_,_=documented
    manager,_=manager_for(documented,tmp_path,monkeypatch)
    entered=threading.Event()
    def blocked(session,token,workdir):
        entered.set();session.stop.wait(5);return True
    monkeypatch.setattr(manager,'_run_cli',blocked)
    manager.review_batches.start('authored',REVIEWER,WRITER)
    assert entered.wait(5)
    with net.store.tx() as db:
        cfg=net.cfg(net._project('authored'));cfg['rom']['size']+=1
        db.execute('UPDATE projects SET config=?',(json.dumps(cfg),))
    assert wait_batch(manager) is None
    saved=json.loads(net.store.one("SELECT value FROM settings WHERE key LIKE 'review_batch:%'")['value'])
    assert saved['state']=='paused' and 'input changed' in saved['reason']
    assert all(s.stop.is_set() for s in manager.sessions.values())


def test_disappearing_project_does_not_leave_a_batch_helper_running(documented,tmp_path,monkeypatch):
    net,_,_=documented
    manager,_=manager_for(documented,tmp_path,monkeypatch)
    entered=threading.Event()
    def blocked(session,token,workdir):
        entered.set();session.stop.wait(5);return True
    monkeypatch.setattr(manager,'_run_cli',blocked)
    manager.review_batches.start('authored',REVIEWER,WRITER)
    assert entered.wait(5)
    with net.store.tx() as db:
        db.execute("DELETE FROM projects WHERE slug='authored'")
    deadline=time.monotonic()+5
    while manager.review_batches.active and time.monotonic()<deadline:
        time.sleep(.01)
    assert not manager.review_batches.active
    assert all(s.stop.is_set() for s in manager.sessions.values())
