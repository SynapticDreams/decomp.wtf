"""Run an authored DOM harness with an available Chromium browser."""
import html
from pathlib import Path
import re
import shutil
import subprocess

import pytest


def run(tmp_path, scripts):
    chromium = shutil.which('google-chrome') or shutil.which('chromium') or shutil.which('chromium-browser')
    if chromium is None:
        pytest.skip('requires local Chrome or Chromium for the authored browser check')
    root = Path(__file__).resolve().parents[1]
    page = tmp_path / 'harness.html'
    content = '<!doctype html><meta charset="utf-8"><div id="panel"></div><pre id="report">RUNNING</pre>'
    page.write_text(content + ''.join('<script>' + (root / path).read_text().replace('</script', '<\\/script') + '</script>'
                                     for path in scripts))
    result = subprocess.run([chromium, '--headless', '--no-sandbox', '--disable-gpu', '--disable-dev-shm-usage',
        '--disable-background-networking', '--no-first-run', '--no-default-browser-check', '--virtual-time-budget=5000',
        f'--user-data-dir={tmp_path / "browser"}', '--dump-dom', page.as_uri()], text=True, capture_output=True, timeout=60)
    report = re.search(r'<pre id="report">(.*?)</pre>', result.stdout, re.S)
    assert result.returncode == 0 and report is not None, result.stderr[-1000:]
    assert html.unescape(report[1]).startswith('PASS:'), html.unescape(report[1])
