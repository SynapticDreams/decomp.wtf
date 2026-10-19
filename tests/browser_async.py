"""Run native asynchronous file/DOM fixtures to completion using an available browser and Node WebSocket."""
from pathlib import Path
import shutil
import subprocess
import time

import pytest


def run(chromium, page, tmp_path):
    node = shutil.which('node')
    if node is None:
        pytest.skip('async browser checks need Node WebSocket')
    flags = []
    probe = subprocess.run([node, '-p', 'typeof WebSocket'], capture_output=True, text=True, timeout=5)
    if probe.returncode or probe.stdout.strip() != 'function':
        flags = ['--experimental-websocket']
        probe = subprocess.run([node, *flags, '-p', 'typeof WebSocket'], capture_output=True, text=True, timeout=5)
    if probe.returncode or probe.stdout.strip() != 'function':
        pytest.skip('async browser checks need Node WebSocket')
    profile = tmp_path / 'async-browser'
    with (tmp_path / 'browser.log').open('w') as log:
        process = subprocess.Popen([chromium, '--headless', '--no-sandbox', '--disable-gpu', '--disable-dev-shm-usage',
            '--disable-background-networking', '--no-first-run', '--no-default-browser-check',
            '--remote-debugging-port=0', f'--user-data-dir={profile}', 'about:blank'], stdout=log, stderr=log)
        try:
            deadline = time.monotonic() + 10
            active = profile / 'DevToolsActivePort'
            address = []
            while process.poll() is None and time.monotonic() < deadline:
                try:
                    address = active.read_text().splitlines()
                    if len(address) >= 2 and address[0].isdigit() and address[1].startswith('/devtools/browser/'):
                        break
                except FileNotFoundError:
                    pass
                time.sleep(0.02)
            assert len(address) >= 2, 'browser debugger did not start'
            port, endpoint = address[:2]
            driver = Path(__file__).with_name('browser_driver.js')
            result = subprocess.run([node, *flags, str(driver), f'ws://127.0.0.1:{port}{endpoint}',
                                     page.as_uri()], capture_output=True, text=True, timeout=20)
            assert result.returncode == 0 and result.stdout.startswith('PASS:'), result.stdout + result.stderr
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill(); process.wait(timeout=5)
