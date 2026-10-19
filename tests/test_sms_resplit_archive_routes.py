"""Saved text has a separate authenticated, read-only operator route."""
import hashlib

from starlette.testclient import TestClient

from decompnet.app.server import build

from .test_sms_resplit_archive import project as fixture_project, saved as fixture_saved, capture

project, saved = fixture_project, fixture_saved


def test_archive_route_requires_operator_auth_and_never_mutates_current_work(saved, tmp_path):
    net, slug, hid, fid, text = saved
    before = capture(net, slug)
    port, secret = 6484, 'archive-fixture-secret'
    mcp, _manager, security = build(net, tmp_path, port, secret)
    app = mcp.streamable_http_app(transport_security=security, host='127.0.0.1')
    with TestClient(app, base_url=f'http://127.0.0.1:{port}') as client:
        url = '/api/resplit/archive'
        params = {'slug': slug, 'history': hid, 'function': fid, 'item': 'best', 'limit': 262144}
        assert client.get(url, params=params).status_code == 401
        client.cookies.set('decomp_live', secret)
        assert client.post(url, json=params, headers={'X-Decomp': '1'}).status_code == 405
        listing = client.get(url, params={'slug': slug, 'history': hid}).json()
        assert listing['functions'] and text not in str(listing)
        response = client.get(url, params=params)
        assert response.status_code == 200, response.text
        assert response.json()['text'] == text and response.json()['next_start'] is None
        assert response.json()['sha256'] == hashlib.sha256(text.encode()).hexdigest()
        assert client.get(url, params={**params, 'history': 'invalid'}).status_code == 400
        assert client.get(url, params={**params, 'history': 999999}).status_code == 400
        assert client.get(url, params={**params, 'item': 'attempt:999999'}).status_code == 400
        assert client.get(url, params={**params, 'limit': 262145}).status_code == 400
        assert 'ResplitArchiveUI' in client.get('/assets/resplit-archive.js').text
        assert '/assets/resplit-archive.js' in client.get('/').text
    assert capture(net, slug) == before
