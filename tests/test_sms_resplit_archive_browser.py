"""Run authored recovery interactions against actual DOM behavior."""
from .browser_check import run


def test_archive_browser_recovery_and_stale_response_guards(tmp_path):
    run(tmp_path, [f'src/decompnet/app/static/{name}' for name in ('resplit-archive.js', 'resplit-history.js')] +
        ['tests/browser/sms_resplit_archive.js'])
