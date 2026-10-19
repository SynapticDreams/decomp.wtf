"""Preview inspection is an authenticated, read-only operator job with a fingerprint."""
from starlette.testclient import TestClient

from decompnet.app.server import build

from .test_sms_profile_migration import project as fixture_project, proposal, snapshot
from .test_sms_profile_migration_routes import completed

project = fixture_project


def test_operator_inspects_the_same_profile_preview_without_saving_or_stopping_analysis(project, tmp_path, monkeypatch):
    net, slug = project
    port, secret = 6506, 'inspection-fixture-secret'
    mcp, _manager, security = build(net, tmp_path, port, secret)
    app = mcp.streamable_http_app(transport_security=security, host='127.0.0.1')
    stops = []
    monkeypatch.setattr(net.permuter, 'stop', lambda *_: stops.append('permuter'))
    monkeypatch.setattr(net, 'stop_autopilot', lambda *_: stops.append('autopilot'))
    before = snapshot(net, slug)
    with TestClient(app, base_url=f'http://127.0.0.1:{port}') as client:
        headers = {'X-Decomp': '1'}
        profile = {'slug': slug, 'profile': proposal()}
        assert client.post('/api/resplit', json=profile, headers=headers).status_code == 401
        client.cookies.set('decomp_live', secret)
        preview = completed(client, client.post('/api/resplit', json=profile, headers=headers))['result']
        body = {**profile, 'plan': preview['plan'], 'inspection': {'kind': 'changed', 'offset': 0}}
        assert client.post('/api/resplit', json=body).status_code == 403
        assert client.post('/api/resplit', json={**body, 'apply': True}, headers=headers).status_code == 400
        assert client.post('/api/resplit', json={**body, 'undo': 1}, headers=headers).status_code == 400
        net.autopilots[slug] = {'state': 'running'}  # Reading a coherent snapshot may run alongside analysis.
        result = completed(client, client.post('/api/resplit', json=body, headers=headers))
        assert result['state'] == 'done', result['error']
        assert result['result'] == {'plan': preview['plan'], 'inspection': {
            'kind': 'changed', 'offset': 0, 'total': 0, 'limit': 100, 'next_offset': None, 'rows': []}}
        stale = completed(client, client.post('/api/resplit', json={**body, 'profile': proposal('codemasters')}, headers=headers))
        assert stale['state'] == 'error' and 'stale' in stale['error']
        missing = {key: value for key, value in body.items() if key != 'plan'}
        refused = completed(client, client.post('/api/resplit', json=missing, headers=headers))
        assert refused['state'] == 'error' and 'preview before' in refused['error']
        assert '/assets/resplit-inspection.js' in client.get('/').text
        assert 'ResplitInspectionUI' in client.get('/assets/resplit-inspection.js').text
    assert not stops and snapshot(net, slug) == before and not net.resplit_history(slug)['history']
