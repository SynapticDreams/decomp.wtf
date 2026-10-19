"""Serve the real guarded app to an authored browser fixture on a task-owned loopback socket."""
from pathlib import Path
import shutil
import socket
import threading
import time
from types import SimpleNamespace
import json

import pytest
from starlette.responses import HTMLResponse
from starlette.routing import Route
import uvicorn

from decompnet.app.server import build
from .browser_async import run

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ['research-json.js', 'sms-research-templates.js', 'sms-research-view.js', 'sms-research-draft.js', 'sms-research.js']


def live(net, slug, tmp_path):
    browser = shutil.which('google-chrome') or shutil.which('chromium') or shutil.which('chromium-browser')
    if browser is None:
        pytest.skip('requires Chrome or Chromium for the real HTTP/browser workflow')
    sock = socket.socket()
    sock.bind(('127.0.0.1', 0))
    port = sock.getsockname()[1]
    mcp, _manager, security = build(net, tmp_path, port, 'authored-browser-session')
    app = mcp.streamable_http_app(transport_security=security, host='127.0.0.1')
    static = ROOT / 'src/decompnet/app/static'
    page = (static / 'index.html').read_text()
    markup = page[page.index('<div id="smsResearch"'):page.index('<h3 class="sub" id="symHead"')]
    api = (static / 'app.js').read_text().split('let apiRetried = false;')[1].split('\nfunction toast(')[0]
    symbol = net.store.one('SELECT name FROM functions WHERE project_id=? AND rom_offset=512', net.project_row(slug)['id'])['name']
    setup = 'window.researchFixture=' + json.dumps({'overview': net.overview(slug), 'symbol': symbol}) + ';'
    content = '<!doctype html><meta charset="utf-8"><link rel="stylesheet" href="/assets/app.css"><pre id="report">RUNNING</pre>' + markup
    scripts = [setup, 'let apiRetried = false;' + api, *[(static / name).read_text() for name in SCRIPTS],
               (ROOT / 'tests/browser/sms_research_live.js').read_text()]
    content += ''.join('<script>' + script.replace('</script', '<\\/script') + '</script>' for script in scripts)

    async def fixture(_request):
        response = HTMLResponse(content)
        response.set_cookie('decomp_live', 'authored-browser-session', httponly=True, samesite='strict')
        return response

    app.routes.insert(0, Route('/research-ui-fixture', fixture))
    server = uvicorn.Server(uvicorn.Config(app, log_level='error', lifespan='on'))
    errors = []

    def serve():
        try:
            server.run(sockets=[sock])
        except BaseException as exc:
            errors.append(exc)

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 10
        while thread.is_alive() and not server.started and time.monotonic() < deadline:
            time.sleep(0.02)
        assert server.started and not errors, f'fixture server did not start: {errors}'
        run(browser, SimpleNamespace(as_uri=lambda: f'http://127.0.0.1:{port}/research-ui-fixture'), tmp_path)
    finally:
        server.should_exit = True
        thread.join(10)
        if thread.is_alive():
            server.force_exit = True
            thread.join(5)
        sock.close()
        assert not thread.is_alive(), 'fixture server did not stop'
        assert not errors, errors
