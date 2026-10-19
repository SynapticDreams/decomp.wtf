"""Existing HTTP correction endpoint keeps operator review behind cookie/header guards."""
import pytest
from starlette.testclient import TestClient

from decompnet.app.server import build
from .test_sms_correction_facts import project as fixture_project, draft

project = fixture_project


def test_authenticated_proposal_inspection_review_and_undo_use_existing_routes(project, tmp_path):
    net, slug = project
    mcp, _manager, security = build(net, tmp_path, 6509, 'correction-fixture-secret')
    app = mcp.streamable_http_app(transport_security=security, host='127.0.0.1')
    headers = {'X-Decomp': '1'}
    with TestClient(app, base_url='http://127.0.0.1:6509') as client:
        body = {'slug': slug, **draft('code'), 'apply': False}
        assert client.post('/api/corrections', json=body, headers=headers).status_code == 401
        client.cookies.set('decomp_live', 'correction-fixture-secret')
        assert client.post('/api/corrections', json=body).status_code == 403
        preview = client.post('/api/corrections', json=body, headers=headers)
        assert preview.status_code == 200, preview.text
        assert not preview.json()['applied']
        invalid = client.post('/api/corrections', json={**body, 'apply': True}, headers=headers)
        assert invalid.status_code == 400
        stored = client.post('/api/corrections', json={**body, 'apply': True, 'expected_plan': preview.json()['plan']}, headers=headers)
        assert stored.status_code == 200, stored.text
        cid = stored.json()['correction']['id']
        assert not stored.json()['correction']['active']
        inspected = client.get('/api/corrections', params={'slug': slug, 'id': cid})
        assert inspected.status_code == 200 and inspected.json()['binding'] == 'current'
        review = {'slug': slug, 'action': 'review', 'id': cid, 'ok': True}
        assert client.post('/api/corrections', json=review).status_code == 403
        decision = client.post('/api/corrections', json=review, headers=headers)
        assert decision.status_code == 200, decision.text
        accepted = client.post('/api/corrections', json={**review, 'apply': True, 'expected_plan': decision.json()['plan']}, headers=headers)
        assert accepted.status_code == 200 and accepted.json()['correction']['active'], accepted.text
        assert client.post('/api/corrections/undo', json={'slug': slug, 'id': True}, headers=headers).status_code == 400
        undone = client.post('/api/corrections/undo', json={'slug': slug, 'id': cid}, headers=headers)
        assert undone.status_code == 200 and undone.json()['corrections'][0]['undone']
        for params in ({'id': 0}, {'limit': 501}, {'before_id': -1}):
            assert client.get('/api/corrections', params={'slug': slug, **params}).status_code == 400


@pytest.mark.parametrize('field,value', [('apply', 1), ('count', True), ('count', '2')])
def test_http_does_not_coerce_invalid_correction_arguments(project, tmp_path, field, value):
    net, slug = project
    mcp, _manager, security = build(net, tmp_path, 6509, 'strict-fixture-secret')
    with TestClient(mcp.streamable_http_app(transport_security=security, host='127.0.0.1'), base_url='http://127.0.0.1:6509') as client:
        client.cookies.set('decomp_live', 'strict-fixture-secret')
        body = {'slug': slug, **draft('data'), 'apply': False, field: value}
        result = client.post('/api/corrections', json=body, headers={'X-Decomp': '1'})
        assert result.status_code == 400, result.text
        assert not net.store.all('SELECT * FROM corrections')
