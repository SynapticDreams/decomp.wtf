"""Production drawer, dialogs and guarded API on a task-owned server; no real helpers launched."""
from pathlib import Path
import re
import shutil
import socket
import threading
import time
from types import SimpleNamespace

import pytest
from starlette.responses import HTMLResponse, Response
from starlette.routing import Route
import uvicorn

from decompnet.app import agents
from decompnet.app.server import build
from .browser_async import run


def live(net, tmp_path, monkeypatch):
    browser = shutil.which('google-chrome') or shutil.which('chromium') or shutil.which('chromium-browser')
    if not browser:
        pytest.skip('requires Chromium for the production assembly drawer')
    sock = socket.socket(); sock.bind(('127.0.0.1', 0))
    port = sock.getsockname()[1]
    monkeypatch.setattr(agents.Manager, '_run', lambda self, session: None)
    mcp, manager, security = build(net, tmp_path / '.decomp', port, 'authored-browser-session')
    app = mcp.streamable_http_app(transport_security=security, host='127.0.0.1')
    root = Path(__file__).resolve().parents[1]
    static = root / 'src/decompnet/app/static'
    content = (static / 'index.html').read_text()
    # Keep production functions and event handlers; this fixture drives state instead of the home-page boot.
    script = (static / 'app.js').read_text().replace('loadNav();\nroute();', '')
    script = re.sub(r'setTimeout\(\(\) => checkUpdate\(false, true\), 4000\);', '', script)
    script = re.sub(r'setInterval\(\(\) => checkUpdate\(false, true\), 10 \* 60 \* 1000\);', '', script)
    content = content.replace('/assets/app.js', '/assembly-fixture-app.js')
    fixture = (root / 'tests/browser/assembly_work_live.js').read_text()
    content = content.replace('</body>', '<pre id="report">RUNNING</pre><script src="/assembly-fixture-test.js"></script></body>')

    async def fixture_app(_request):
        return Response(script, media_type='text/javascript')

    async def fixture_test(_request):
        return Response(fixture, media_type='text/javascript')

    async def page(_request):
        response = HTMLResponse(content)
        response.set_cookie('decomp_live', 'authored-browser-session', httponly=True, samesite='strict')
        return response

    app.routes.insert(0, Route('/assembly-ui-fixture', page))
    app.routes.insert(0, Route('/assembly-fixture-app.js', fixture_app))
    app.routes.insert(0, Route('/assembly-fixture-test.js', fixture_test))
    server = uvicorn.Server(uvicorn.Config(app, log_level='error'))
    thread = threading.Thread(target=lambda: server.run(sockets=[sock]), daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 10
        while not server.started and thread.is_alive() and time.monotonic() < deadline:
            time.sleep(.02)
        assert server.started
        run(browser, SimpleNamespace(as_uri=lambda: f'http://127.0.0.1:{port}/assembly-ui-fixture'), tmp_path)
    finally:
        server.should_exit = True; thread.join(10); sock.close()
        assert not thread.is_alive()
    return manager
