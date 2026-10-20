"""Authored assembly reviews: independent helpers, read-only tools and source-bound advice."""
import asyncio
import json

import httpx
import pytest
from mcp.server.mcpserver.exceptions import ToolError
from starlette.testclient import TestClient

from decompnet.app import agents, tools
from decompnet.app.server import build
from decompnet.network import NetworkError
from .test_assembly_work import work  # noqa: F401


@pytest.fixture
def documented(work):  # noqa: F811
    net, writer, verdict = work
    verdict.ok = True; verdict.problems = []; verdict.text = '; Return to the caller.\nFirst: ret'; verdict.label = 'First'
    net.document_function(writer, 'authored', 'First', verdict.text)
    with net.store.tx() as db:
        meta = json.loads(net._function('First', 'authored')['meta']); meta['sample'] = True
        db.execute("UPDATE functions SET meta=? WHERE name='First'", (json.dumps(meta),))
    reviewer, _ = net.local_agent('review-test')
    return net, writer, reviewer


def begin(documented):
    net, _, reviewer = documented
    net.documentation_review.begin(reviewer, 'authored', 'First', kind='api', model='authored-review-model')
    return json.loads(tools.call(net, reviewer, 'authored', 'get_documentation_review', {}))


def report(inputs, **overrides):
    return {'function': 'First', 'review_context': inputs['review_context'], 'verdict': 'supported',
            'summary': 'This routine immediately returns to its caller and performs no work.',
            'evidence': ['At the entry at 0x0100, the only instruction is RET; no memory is modified.'],
            'concerns': [], **overrides}


@pytest.mark.parametrize('verdict', ['supported', 'uncertain', 'needs_changes'])
def test_reports_never_approve_reopen_or_edit_documentation(documented, verdict):
    net, _, reviewer = documented
    inputs = begin(documented)
    before = dict(net._function('First', 'authored'))
    args = report(inputs, verdict=verdict, concerns=[] if verdict == 'supported' else ['The claimed wider purpose is not established by this one instruction.'])
    assert tools.call(net, reviewer, 'authored', 'submit_documentation_review', args).startswith('AI review saved')
    fn = net._function('First', 'authored')
    for field in ('status', 'matched_source', 'matched_agent_id', 'best_source', 'attempts'):
        assert fn[field] == before[field]
    assert json.loads(fn['meta'])['sample']
    result = net.function_detail('authored', 'First')['documentation_reviews'][0]
    assert result['current'] and result['verdict'] == verdict and result['model'] == 'authored-review-model'
    assert result['reviewer'] != 'writer'
    assert not net.store.one('SELECT 1 FROM claims')
    assert 'already saved' in tools.call(net, reviewer, 'authored', 'submit_documentation_review', args)


def test_writer_cannot_review_itself_and_ordinary_helpers_cannot_submit(documented):
    net, writer, _ = documented
    with pytest.raises(NetworkError, match='fresh helper'):
        net.documentation_review.begin(writer, 'authored', 'First')
    assert 'dedicated AI' in tools.call(net, writer, 'authored', 'submit_documentation_review', report({'review_context': 'fake'}))


@pytest.mark.parametrize('platform,arch', [('gb', 'sm83'), ('gbc', 'sm83'), ('sms', 'z80'), ('gg', 'z80'), ('nes', 'mos6502')])
def test_review_inputs_support_every_assembly_platform(documented, platform, arch):
    net, _, _ = documented
    with net.store.tx() as db:
        cfg = net.cfg(net._project('authored')); cfg.update(platform=platform, arch=arch)
        if platform == 'nes':
            cfg['rom'].update(prg_offset=16, bank_size=0x4000, mapper=0)
            db.execute("UPDATE functions SET target=?,asm='rts'", (b'\x60',))
        db.execute('UPDATE projects SET arch=?,config=?', (arch, json.dumps(cfg)))
    inputs = begin(documented)
    assert inputs['platform'] == platform and inputs['source'] and inputs['target_assembly']
    assert inputs['mapper'] is not None and inputs['address'] == 0x100 and inputs['symbols']['First'] == 0x100


@pytest.mark.parametrize('name,args', [
    ('claim_function', {}), ('compile_and_diff', {'function': 'First', 'source': 'changed'}),
    ('rename_symbol', {'old': 'First', 'new': 'Changed'}), ('add_note', {'text': 'An unsolicited mutation'}),
    ('edit_context', {'old': '', 'new': 'changed', 'message': 'changed'}),
    ('correct_split', {'kind': 'code', 'at': '0x100', 'reason': 'changed'}),
    ('defer_documentation', {'function': 'Second', 'reason': 'Unsolicited deferral'}),
])
def test_hidden_mutation_tools_are_enforced_for_api_and_mcp(documented, name, args):
    net, _, reviewer = documented
    begin(documented)
    assert 'read-only' in tools.call(net, reviewer, 'authored', name, args)
    mcp = tools.build_mcp(net, lambda _ctx: (reviewer, 'authored'))
    async def invoke():
        with pytest.raises(ToolError, match='read-only'):
            await mcp.call_tool(name, args)
    # MCP validates schemas first; exercise a fully valid mutation through its real dispatcher.
    if name in ('claim_function', 'compile_and_diff', 'add_note', 'edit_context', 'defer_documentation'):
        asyncio.run(invoke())
    net.documentation_review.active.pop(reviewer.id)
    # A stopped session's still-valid token remains restricted (also after an app restart).
    assert 'dedicated AI' in tools.call(net, reviewer, 'authored', 'claim_function', {})
    assert net._function('First', 'authored')['status'] == 'documented'


@pytest.mark.parametrize('change', ['source', 'target', 'name', 'callee_source', 'profile'])
def test_changed_inputs_reject_submission_and_mark_saved_reports_historical(documented, change):
    net, _, reviewer = documented
    inputs = begin(documented)
    assert 'Second' in tools.call(net, reviewer, 'authored', 'get_function', {'function': 'Second'})
    state = dict(net.documentation_review.active[reviewer.id])
    assert tools.call(net, reviewer, 'authored', 'submit_documentation_review', report(inputs)).startswith('AI review saved')
    net.documentation_review.active[reviewer.id] = {**state, 'done': False}
    with net.store.tx() as db:
        if change == 'source':
            db.execute("UPDATE functions SET matched_source=matched_source || '\n; new explanation' WHERE name='First'")
        elif change == 'target':
            db.execute("UPDATE functions SET target=? WHERE name='First'", (b'\x00',))
        elif change == 'name':
            db.execute("UPDATE functions SET name='Renamed' WHERE name='Second'")
        elif change == 'callee_source':
            db.execute("UPDATE functions SET matched_source='; new helper explanation' WHERE name='Second'")
        else:
            cfg = net.cfg(net._project('authored')); cfg['sms_profile'] = {'evidence': 'new profile'}
            db.execute('UPDATE projects SET config=?', (json.dumps(cfg),))
    out = tools.call(net, reviewer, 'authored', 'submit_documentation_review', report(inputs))
    assert 'changed' in out
    assert not net.function_detail('authored', 'First')['documentation_reviews'][0]['current']
    assert json.loads(net._function('First', 'authored')['meta'])['sample']


@pytest.mark.parametrize('override', [{'evidence': []}, {'verdict': 'approved'}, {'summary': 'ok'},
    {'concerns': ['There is a specific unresolved concern.']}, {'evidence': 'invented'},
    {'verdict': 'uncertain', 'concerns': []}, {'function': 'Second'}, {'review_context': 'wrong'}])
def test_invalid_or_conflicting_reports_are_not_saved(documented, override):
    net, _, reviewer = documented
    inputs = begin(documented)
    assert tools.call(net, reviewer, 'authored', 'submit_documentation_review', report(inputs, **override)).startswith('error:')
    assert not net.function_detail('authored', 'First')['documentation_reviews']


def test_review_launcher_guards_and_isolation(documented, tmp_path, monkeypatch):
    net, _, _ = documented
    mcp, manager, security = build(net, tmp_path / '.decomp', 6497, 'fixture-secret')
    monkeypatch.setattr(manager, '_run', lambda session: None)
    monkeypatch.setattr(manager, '_prepare', lambda slug: pytest.fail('review must not start background preparation'))
    client = TestClient(mcp.streamable_http_app(transport_security=security, host='127.0.0.1'), base_url='http://127.0.0.1:6497')
    body = {'kind': 'claude', 'slug': 'authored', 'options': {'track': 'asm_review', 'pin': 'First', 'polish': True}}
    assert client.post('/api/agents/start', json=body).status_code == 401
    client.cookies.set('decomp_live', 'fixture-secret')
    assert client.post('/api/agents/start', json=body).status_code == 403
    headers = {'X-Decomp': '1'}
    response = client.post('/api/agents/start', json=body, headers=headers)
    assert response.status_code == 200, response.text
    session = manager.sessions[response.json()['started'][0]]
    assert session.agent_name == 'review-claude-1' and not session.options['polish'] and not session.options.get('lean')
    assert 'get_documentation_review' in manager.prompt(session) and 'claim_function ->' not in manager.prompt(session)
    assert client.post('/api/agents/start', json=body, headers=headers).status_code == 400
    for options in [{'pin': 'Second'}, {'pin': ''}, {'lean': 'one'}, {'model': 'tiered'}, {'only_starred': True}]:
        rejected = client.post('/api/agents/start', json={**body, 'options': {**body['options'], **options}}, headers=headers)
        assert rejected.status_code == 400, rejected.text


def test_api_review_uses_only_read_tools_and_stops_after_report(documented, tmp_path, monkeypatch):
    net, _, _ = documented
    manager = agents.Manager(net, tmp_path / '.decomp', 'http://example.invalid/mcp')
    session = agents.Session('api-review', 'api', 'Test reviewer', 'authored', 'review-api',
        {'track': 'asm_review', 'pin': 'First', 'base_url': 'http://example.invalid/v1', 'model': 'authored-model'})
    calls = []
    def handler(request):
        data = json.loads(request.content); calls.append(data)
        assert {t['function']['name'] for t in data['tools']} == set(tools.tool_names(False, True))
        if len(calls) == 1:
            name, args = 'get_documentation_review', {}
        else:
            name, args = 'submit_documentation_review', report(json.loads(data['messages'][-1]['content']))
        return httpx.Response(200, json={'choices': [{'message': {'role': 'assistant', 'tool_calls': [
            {'id': str(len(calls)), 'type': 'function', 'function': {'name': name, 'arguments': json.dumps(args)}}]}}]})
    original = httpx.Client
    monkeypatch.setattr(agents.httpx, 'Client', lambda **kw: original(transport=httpx.MockTransport(handler), **kw))
    manager._run(session)
    assert len(calls) == 2 and session.state == 'stopped' and session.stop.is_set() and not session.error
    assert not net.documentation_review.active and net.function_detail('authored', 'First')['documentation_reviews'][0]['current']
    assert not net.store.one('SELECT 1 FROM claims')
    assert 'submit_documentation_review' not in tools.tool_names(False)


def test_cli_review_without_a_saved_report_stops_with_actionable_error(documented, tmp_path, monkeypatch):
    net, _, _ = documented
    manager = agents.Manager(net, tmp_path / '.decomp', 'http://example.invalid/mcp')
    monkeypatch.setattr(manager, '_run_cli', lambda *args: True)
    session = agents.Session('claude-review', 'claude', 'Test reviewer', 'authored', 'review-cli', {'track': 'asm_review', 'pin': 'First'})
    manager._run(session)
    assert session.state == 'error' and session.runs == 1 and 'without saving' in session.error
    assert not net.documentation_review.active
    assert not net.function_detail('authored', 'First')['documentation_reviews']


def test_send_back_and_layout_changes_do_not_make_a_review_current(documented):
    net, _, reviewer = documented
    inputs = begin(documented)
    tools.call(net, reviewer, 'authored', 'submit_documentation_review', report(inputs))
    net.review_documented('authored', 'First', False, 'The explanation needs a clearer statement of its input.')
    detail = net.function_detail('authored', 'First')
    assert detail['status'] == 'asm' and not detail['documentation_reviews'][0]['current']
    assert detail['source'] == inputs['source']


def test_review_panel_explains_uncertainty_and_stale_reports(tmp_path):
    from .browser_check import run
    run(tmp_path, ['src/decompnet/app/static/assembly-work.js', 'tests/browser/documentation_review.js'])


def test_production_drawer_can_launch_review_and_show_report_without_clearing_flag(documented, tmp_path, monkeypatch):
    from .assembly_browser import live
    net, _, _ = documented
    def review(manager, session, token, workdir):
        agent = net.authenticate(token)
        inputs = json.loads(tools.call(net, agent, 'authored', 'get_documentation_review', {}))
        result = tools.call(net, agent, 'authored', 'submit_documentation_review', report(inputs,
            verdict='uncertain', summary='<img src=x> This routine returns to its caller. Its wider purpose is unknown.',
            concerns=['Read its callers before assigning any game-specific purpose.']))
        assert result.startswith('AI review saved'), result
        return True
    monkeypatch.setattr(agents.Manager, '_run_cli', review)
    manager = live(net, tmp_path, monkeypatch, script_name='documentation_review_live.js', run_helper=True)
    (session,) = manager.sessions.values()
    assert session.options['track'] == 'asm_review' and session.runs == 1 and not session.error
    assert json.loads(net._function('First', 'authored')['meta'])['sample']
