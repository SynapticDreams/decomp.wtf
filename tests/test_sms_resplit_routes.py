"""Operator history routes expose metadata and guard authenticated undo jobs."""
import time

from starlette.testclient import TestClient

from decompnet.app.server import build

from .test_sms_resplit_history import project as fixture_project, snapshot

project = fixture_project


def complete(client, job):
    for _ in range(200):
        result = client.get(f'/api/job?id={job}').json()
        if result['state'] != 'running':
            return result
        time.sleep(0.01)
    raise AssertionError('resplit job did not finish')


def test_authenticated_history_and_undo_round_trip(project, tmp_path):
    net, slug, _proj = project
    before = snapshot(net, slug)
    result = net.resplit_banked(slug, apply=True, log=lambda *_: None)
    port, secret = 6498, 'resplit-fixture-secret'
    mcp, _manager, security = build(net, tmp_path, port, secret)
    app = mcp.streamable_http_app(transport_security=security, host='127.0.0.1')
    with TestClient(app, base_url=f'http://127.0.0.1:{port}') as client:
        assert client.get(f'/api/resplit?slug={slug}').status_code == 401
        client.cookies.set('decomp_live', secret)
        history = client.get(f'/api/resplit?slug={slug}').json()
        assert history['history'][0]['id'] == result['history_id']
        assert 'before_state' not in history['history'][0]
        assert 'ResplitHistoryUI' in client.get('/assets/resplit-history.js').text
        data = {'slug': slug, 'undo': result['history_id']}
        assert client.post('/api/resplit', json=data).status_code == 403
        response = client.post('/api/resplit', json=data, headers={'X-Decomp': '1'})
        assert response.status_code == 200
        job = complete(client, response.json()['job'])
        assert job['state'] == 'done' and job['result'] == {'undone': result['history_id']}, job
        assert snapshot(net, slug) == before
        assert client.get(f'/api/resplit?slug={slug}&before=invalid').status_code == 400
        assert client.post('/api/resplit', json={**data, 'apply': True}, headers={'X-Decomp': '1'}).status_code == 400
        bad = client.post('/api/resplit', json={'slug': slug, 'undo': True}, headers={'X-Decomp': '1'})
        assert complete(client, bad.json()['job'])['state'] == 'error'
