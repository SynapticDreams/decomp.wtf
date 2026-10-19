"""Operator export policy and separate overview evidence travel through actual API jobs."""
import json
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from decompnet.app.server import build
from decompnet.rom import sms_asm

from .test_export_sms import exported as fixture_exported
from .test_sms_profile_migration_routes import completed

exported = fixture_exported
pytestmark = pytest.mark.skipif(not sms_asm.available(), reason='needs WLA-DX')


def test_operator_controls_strict_insertion_and_sees_independent_evidence(exported, tmp_path):
    net, slug, _result, _out = exported
    port, secret = 6508, 'progress-fixture-secret'
    mcp, _manager, security = build(net, tmp_path, port, secret)
    app = mcp.streamable_http_app(transport_security=security, host='127.0.0.1')
    with TestClient(app, base_url=f'http://127.0.0.1:{port}') as client:
        headers = {'X-Decomp': '1'}
        body = {'slug': slug, 'strict_documented': True}
        assert client.post('/api/export', json=body, headers=headers).status_code == 401
        client.cookies.set('decomp_live', secret)
        assert client.post('/api/export', json=body).status_code == 403
        invalid = completed(client, client.post('/api/export', json={**body, 'strict_documented': 'true'}, headers=headers))
        assert invalid['state'] == 'error' and 'boolean' in invalid['error']
        result = completed(client, client.post('/api/export', json=body, headers=headers))
        assert result['state'] == 'done', result['error']
        assert result['result']['verification']['build']['documented']['required']
        overview = client.get('/api/project', params={'slug': slug}).json()
        assert overview['sms_progress']['input']['status'] == 'verified'
        assert overview['export']['current'] and overview['export']['verification']['documented']['required']
        assert overview['export']['verification']['documented']['inserted'] == 1
        assert 'routines' not in overview['export']['verification']['documented']
        assert not overview['sms_progress']['c_reference']['source_linked']
        assert overview['sms_progress']['semantic_review']['approved'] == 0
        assert 'SMSProgressUI' in client.get('/assets/sms-progress.js').text
        assert '/assets/sms-progress.js' in client.get('/').text
        assert 'smsStrict' in client.get('/').text
        cfg = net.cfg(net.project_row(slug))
        cached = json.dumps(cfg['export'])
        assert len(cached) < 10000 and cfg['export']['verification']['image']['equal']


@pytest.mark.parametrize('filename', ['build.json', 'layout.json', 'tools/sms_export_build_run.py', 'tools/sms_export_artifacts.py'])
def test_configuration_or_helper_failure_replaces_a_stale_standalone_success(exported, filename):
    import subprocess
    import sys

    net, slug, _result, out = exported
    platform = net.cfg(net.project_row(slug))['platform']
    (out / filename).unlink()
    result = subprocess.run([sys.executable, 'build.py'], cwd=out, capture_output=True, text=True, timeout=30)
    assert result.returncode != 0
    report = json.loads((Path(out) / 'build' / 'verification.json').read_text())
    assert not report['passed'] and report['process']['stage'] == 'configuration'
    assert not (out / 'build' / f'game.{platform}').exists()
