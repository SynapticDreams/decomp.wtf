"""Saved project context uses the existing authenticated, read-only archive route."""
from starlette.testclient import TestClient

from decompnet.app.server import build

from .test_sms_project_archive import project as fixture_project, saved as fixture_saved, TEXT
from .test_sms_profile_migration import snapshot

project, saved = fixture_project, fixture_saved


def test_operator_recovers_saved_project_text_without_current_function_or_mutation(saved, tmp_path):
    net, slug, hid, note, _orphan = saved
    before = snapshot(net, slug)
    port, secret = 6507, 'project-archive-fixture-secret'
    mcp, _manager, security = build(net, tmp_path, port, secret)
    app = mcp.streamable_http_app(transport_security=security, host='127.0.0.1')
    with TestClient(app, base_url=f'http://127.0.0.1:{port}') as client:
        params = {'slug': slug, 'history': hid, 'scope': 'project', 'item': f'note:{note}', 'limit': 262144}
        assert client.get('/api/resplit/archive', params=params).status_code == 401
        client.cookies.set('decomp_live', secret)
        result = client.get('/api/resplit/archive', params=params)
        assert result.status_code == 200, result.text
        assert result.json()['text'] == TEXT and 'function' not in result.json()
        assert result.json()['project_context']['scope'] == 'project'
        assert client.post('/api/resplit/archive', json=params, headers={'X-Decomp': '1'}).status_code == 405
        for extra in ({'function': 1}, {'scope': 'other'}, {'history': 999999}, {'item': 'attempt:424244'}):
            assert client.get('/api/resplit/archive', params={**params, **extra}).status_code == 400
    assert snapshot(net, slug) == before
