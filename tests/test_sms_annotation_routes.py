"""Note/symbol metadata uses existing operator guards and strict worker tools, without review tools."""
import asyncio
import json

import pytest
from mcp.server.mcpserver.exceptions import ToolError
from starlette.testclient import TestClient

from decompnet.app import tools, agents
from decompnet.app.server import build
from .test_sms_annotation_subjects import project as fixture_project, TEXT, symbol
from .annotation_fixture import annotation, evidence

project = fixture_project


@pytest.mark.parametrize('kind', ['note', 'symbol'])
def test_note_and_symbol_operator_routes_require_authenticated_exact_previews_for_review_and_detachment(project, tmp_path, kind):
    net, slug = project
    mcp, _manager, security = build(net, tmp_path, 6509, 'annotation-fixture-secret')
    endpoint = '/api/note' if kind == 'note' else '/api/symbols/annotation'
    body = {'slug': slug, 'annotation': annotation(), 'evidence': evidence(), 'apply': False,
            **({'text': TEXT} if kind == 'note' else {'symbol': symbol(net, slug)})}
    headers = {'X-Decomp': '1'}
    with TestClient(mcp.streamable_http_app(transport_security=security, host='127.0.0.1'), base_url='http://127.0.0.1:6509') as client:
        assert client.post(endpoint, json=body, headers=headers).status_code == 401
        client.cookies.set('decomp_live', 'annotation-fixture-secret')
        assert client.post(endpoint, json=body).status_code == 403
        preview = client.post(endpoint, json=body, headers=headers)
        assert preview.status_code == 200, preview.text
        assert not preview.json()['applied']
        assert client.post(endpoint, json={**body, 'apply': True}, headers=headers).status_code == 400
        applied = client.post(endpoint, json={**body, 'apply': True, 'expected_plan': preview.json()['plan']}, headers=headers)
        assert applied.status_code == 200, applied.text
        key = applied.json()['record']['key']
        selector = {'id': key} if kind == 'note' else {'symbol': key}
        read = client.get(endpoint, params={'slug': slug, **selector})
        assert read.status_code == 200 and read.json()['binding'] == 'current'
        for action in ('review', 'clear'):
            intent = {'slug': slug, **selector, 'action': action, 'ok': True}
            assert client.post(endpoint, json=intent).status_code == 403
            decision = client.post(endpoint, json=intent, headers=headers)
            assert decision.status_code == 200, decision.text
            result = client.post(endpoint, json={**intent, 'apply': True, 'expected_plan': decision.json()['plan']}, headers=headers)
            assert result.status_code == 200, result.text
            assert result.json()['record']['application'] == ('reviewed_research' if action == 'review' else 'legacy_unknown')
        if kind == 'note':
            plain = client.post(endpoint, json={'slug': slug, 'text': 'Legacy plaintext notes still work.'}, headers=headers)
            assert plain.status_code == 200 and 'message' in plain.json()


def test_actual_mcp_note_symbol_and_inspection_tools_preserve_plaintext_calls_and_do_not_expose_review(project):
    net, slug = project
    agent, _ = net.local_agent('metadata_mcp')
    mcp = tools.build_mcp(net, lambda _context: (agent, slug))
    async def exercise():
        names = {item.name for item in await mcp.list_tools()}
        assert {'add_note', 'annotate_symbol', 'inspect_annotations'} <= names
        assert not {'review_annotation', 'clear_annotation'} & names
        plain = await mcp.call_tool('add_note', {'text': 'A plaintext compatibility observation.'})
        assert plain.content[0].text.startswith('Noted.')
        args = {'text': TEXT, 'annotation': annotation(), 'evidence': evidence(), 'apply': False}
        preview = await mcp.call_tool('add_note', args)
        result = json.loads(preview.content[0].text)
        assert not result['applied'] and result['record']['application'] == 'pending_review'
        applied = await mcp.call_tool('add_note', {**args, 'apply': True, 'expected_plan': result['plan']})
        cid = json.loads(applied.content[0].text)['record']['key']
        inspected = await mcp.call_tool('inspect_annotations', {'kind': 'note', 'key': cid})
        assert json.loads(inspected.content[0].text)['subject']['value']['entity']['text'] == TEXT
        sym = await mcp.call_tool('annotate_symbol', {'symbol': symbol(net, slug), 'annotation': annotation(), 'apply': False})
        assert json.loads(sym.content[0].text)['record']['application'] == 'pending_review'
        for name, bad in [('add_note', {'text': TEXT, 'apply': 1}),
                          ('annotate_symbol', {'symbol': symbol(net, slug), 'apply': 1}),
                          ('inspect_annotations', {'kind': 'note', 'key': True})]:
            with pytest.raises(ToolError):
                await mcp.call_tool(name, bad)
    asyncio.run(exercise())
    builtin = {item['function']['name'] for item in agents.api_tool_schemas()}
    assert {'annotate_symbol', 'inspect_annotations'} <= builtin
    assert not {'review_annotation', 'clear_annotation'} & builtin
    assert 'annotate_symbol' not in tools.tool_names(fork=True)
