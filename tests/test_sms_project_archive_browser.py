"""Project-context copy/download and stale-response behavior use the actual archive component."""
from .browser_check import run


def test_saved_project_context_browser_without_functions(tmp_path):
    run(tmp_path, ['src/decompnet/app/static/resplit-archive.js', 'tests/browser/sms_project_archive.js'])
