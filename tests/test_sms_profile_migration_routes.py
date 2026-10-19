"""Profile migration uses the authenticated operator resplit job and existing helper guards."""
from threading import Event
import time
from types import SimpleNamespace

from starlette.testclient import TestClient

from decompnet.app.server import build

from .test_sms_profile_migration import project as fixture_project, proposal, snapshot

project = fixture_project


def completed(client, response):
    assert response.status_code == 200, response.text
    job = response.json()['job']
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        result = client.get('/api/job', params={'id': job}).json()
        if result['state'] != 'running':
            return result
        time.sleep(.01)
    raise AssertionError('authored migration job did not finish within its limit')


def test_operator_migrates_the_previewed_profile_and_recovers_through_history(project, tmp_path):
    net, slug = project
    port, secret = 6505, 'migration-fixture-secret'
    mcp, manager, security = build(net, tmp_path, port, secret)
    app = mcp.streamable_http_app(transport_security=security, host='127.0.0.1')
    with TestClient(app, base_url=f'http://127.0.0.1:{port}') as client:
        body = {'slug': slug, 'profile': proposal()}
        headers = {'X-Decomp': '1'}
        assert client.post('/api/resplit', json=body, headers=headers).status_code == 401
        client.cookies.set('decomp_live', secret)
        assert client.post('/api/resplit', json=body).status_code == 403
        before = snapshot(net, slug)
        result = completed(client, client.post('/api/resplit', json=body, headers=headers))
        assert result['state'] == 'done', result['error']
        preview = result['result']
        assert snapshot(net, slug) == before
        manager.sessions['authored'] = SimpleNamespace(slug=slug, state='working', stop=Event())
        apply = {**body, 'apply': True, 'plan': preview['plan']}
        assert client.post('/api/resplit', json=apply, headers=headers).status_code == 400
        manager.sessions.clear()
        assert client.post('/api/resplit', json={**apply, 'undo': 1}, headers=headers).status_code == 400
        stale = completed(client, client.post('/api/resplit', json={**apply, 'profile': proposal('codemasters')}, headers=headers))
        assert stale['state'] == 'error' and 'stale' in stale['error']
        assert snapshot(net, slug) == before
        applied = completed(client, client.post('/api/resplit', json=apply, headers=headers))
        assert applied['state'] == 'done', applied['error']
        assert net.cfg(net.project_row(slug))['sms_profile']['mapper'] == 'mapperless'
        hid = applied['result']['history_id']
        summary = client.get('/api/resplit', params={'slug': slug}).json()['history'][0]['summary']
        assert summary['profile_transition'] == preview['profile_transition']
        restored = completed(client, client.post('/api/resplit', json={'slug': slug, 'undo': hid}, headers=headers))
        assert restored['state'] == 'done' and snapshot(net, slug) == before
        assert 'SMSProfileMigrationUI' in client.get('/assets/sms-profile-migration.js').text
        assert '/assets/sms-profile-migration.js' in client.get('/').text
