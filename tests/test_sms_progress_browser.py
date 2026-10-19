"""Separate progress and build-policy outcomes are rendered by the actual DOM component."""
from .browser_check import run


def test_progress_browser_separates_historical_equality_source_policy_and_unqualified_claims(tmp_path):
    run(tmp_path, ['src/decompnet/app/static/sms-progress.js', 'tests/browser/sms_progress.js'])
