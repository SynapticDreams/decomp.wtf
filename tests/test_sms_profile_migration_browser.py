"""Exercise the actual profile component's preview/apply and stale-result behavior."""
from .browser_check import run


def test_profile_migration_browser_preview_apply_edit_and_project_guards(tmp_path):
    run(tmp_path, [f'src/decompnet/app/static/{name}' for name in
                  ('sms-profile.js', 'sms-profile-migration.js', 'resplit-history.js')] +
        ['tests/browser/sms_profile_migration.js'])
