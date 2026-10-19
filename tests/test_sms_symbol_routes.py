"""Authenticated symbol preview/apply/inspection keeps exact private bytes out of responses."""
import base64
import json
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from decompnet.app.server import build
from decompnet.rom import sms_asm, wla_bundle
from .test_sms_symbol_import import project as fixture_project

project = fixture_project
pytestmark = pytest.mark.skipif(not sms_asm.available(), reason='needs pinned WLA-DX')


def test_authenticated_preview_apply_and_inspection_preserve_binary_source_without_exposing_it(project, tmp_path):
    net, slug, _image, raw, layout = project
    raw = b'\xef\xbb\xbf; authored-private-comment\r\n' + raw.replace(b'\n', b'\r\n')
    raw += b'\r\n[labels]\r\n' + b'\r\n'.join(f'01:2100 Alias_{n}'.encode() for n in range(70))
    mcp, _manager, security = build(net, tmp_path, 6509, 'symbol-fixture-secret')
    app = mcp.streamable_http_app(transport_security=security, host='127.0.0.1')
    with TestClient(app, base_url='http://127.0.0.1:6509') as client:
        body = {'slug': slug, 'source_base64': base64.b64encode(raw).decode(), 'layout': layout,
                'name': 'fixture.sym', 'apply': False}
        headers = {'X-Decomp': '1'}
        assert client.post('/api/symbols/import', json=body, headers=headers).status_code == 401
        client.cookies.set('decomp_live', 'symbol-fixture-secret')
        assert client.post('/api/symbols/import', json=body).status_code == 403
        preview = client.post('/api/symbols/import', json=body, headers=headers)
        assert preview.status_code == 200, preview.text
        assert not preview.json()['applied']
        assert preview.json()['symbol_file']['next_offset'] == 50
        more = client.post('/api/symbols/import', json={**body, 'offset': 50, 'expected_plan': preview.json()['plan']}, headers=headers)
        assert more.status_code == 200, more.text
        assert more.json()['symbol_file']['offset'] == 50 and more.json()['symbol_file']['source_id'] == preview.json()['symbol_file']['source_id']
        assert not (Path(net.project_row(slug)['root']) / '.symbol-imports').exists()
        applied = client.post('/api/symbols/import', json={**body, 'apply': True, 'expected_plan': preview.json()['plan']}, headers=headers)
        assert applied.status_code == 200, applied.text
        assert applied.json()['renamed'] == 0
        stale_page = client.post('/api/symbols/import', json={**body, 'offset': 50, 'expected_plan': preview.json()['plan']}, headers=headers)
        assert stale_page.status_code == 400
        source = applied.json()['symbol_file']['source_id']
        inspected = client.post('/api/symbols/inspect', json={'slug': slug, 'expected_source': source}, headers=headers)
        assert inspected.status_code == 200 and len(inspected.json()['records']) <= 50
        assert not inspected.json()['semantic_approval']
        assert '/assets/sms-symbols.js' in client.get('/').text
        assert 'data-symbol="preview"' in client.get('/').text
        assert 'SMSSymbolUI' in client.get('/assets/sms-symbols.js').text
        assert 'authored-private-comment' not in inspected.text and 'game.asm' not in inspected.text
        cfg = net.cfg(net.project_row(slug))
        payload = json.loads(wla_bundle.verified(Path(net.project_row(slug)['root']), cfg['symbol_file']))
        assert base64.b64decode(payload['source']) == raw
        stale = client.post('/api/symbols/inspect', json={'slug': slug, 'expected_source': '0' * 64}, headers=headers)
        assert stale.status_code == 400
        invalid = client.post('/api/symbols/import', json={**body, 'apply': 1}, headers=headers)
        assert invalid.status_code == 400
