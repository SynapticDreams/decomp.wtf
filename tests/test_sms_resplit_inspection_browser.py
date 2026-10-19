"""Inspect large preview records with the actual DOM components, including stale results."""
from .browser_check import run


def test_preview_inspection_browser_pages_overlaps_and_invalidates_stale_proposals(tmp_path):
    run(tmp_path, [f'src/decompnet/app/static/{name}' for name in
                  ('sms-profile.js', 'sms-profile-migration.js', 'resplit-history.js', 'resplit-inspection.js')] +
        ['tests/browser/sms_resplit_inspection.js'])
