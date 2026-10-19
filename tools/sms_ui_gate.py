"""Execute the SMS/GG operator UI in a real browser and refuse missing tools or skipped cases."""
import argparse
from pathlib import Path
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
TESTS = ('tests/test_sms_research_browser.py', 'tests/test_research_json.py', 'tests/test_sms_ui_gate.py')
LIVE = 'test_research_controls_create_all_kinds_review_and_preserve_subjects_over_real_http'
REQUIRED = {
    'tests.test_sms_research_browser': {f'{LIVE}[{p}]' for p in ('sms', 'gg')} | {
        'test_research_controls_bound_pages_and_ignore_stale_previews_inspections_and_projects'},
    'tests.test_research_json': {'test_research_editor_json_agrees_with_backend_codec_for_exact_and_invalid_values'},
}


def require_tools():
    browser = shutil.which('google-chrome') or shutil.which('chromium') or shutil.which('chromium-browser')
    node = shutil.which('node')
    if not browser or not node:
        raise ValueError('SMS UI gate requires Chrome/Chromium and Node with WebSocket support')
    versions = []
    for tool in (browser, node):
        result = subprocess.run([tool, '--version'], capture_output=True, text=True, timeout=10)
        if result.returncode or not result.stdout.strip():
            raise ValueError('SMS UI gate could not determine a required tool version')
        versions.append(result.stdout.strip())
    return versions


def verify_report(report):
    try:
        cases = list(ET.parse(report).getroot().iter('testcase'))
    except (OSError, ET.ParseError) as exc:
        raise ValueError('SMS UI gate requires a valid fresh test report') from exc
    if not cases or any(case.find(tag) is not None for case in cases for tag in ('skipped', 'failure', 'error')):
        raise ValueError('SMS UI gate requires executed passing tests with zero skips')
    for module, names in REQUIRED.items():
        if not names <= {case.get('name') for case in cases if case.get('classname') == module}:
            raise ValueError('SMS UI gate is missing required browser, platform or JSON checks')
    if not all(any(case.get('classname') == test.removesuffix('.py').replace('/', '.') for case in cases) for test in TESTS):
        raise ValueError('SMS UI gate is missing a required test module')
    return len(cases)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report', type=Path, default=ROOT / 'build/sms-ui-gate.xml')
    args = parser.parse_args()
    try:
        print('SMS UI gate tools: ' + '; '.join(require_tools()), flush=True)
        report = args.report.resolve()
        report.parent.mkdir(parents=True, exist_ok=True)
        report.unlink(missing_ok=True)
        result = subprocess.run([sys.executable, '-m', 'pytest', '-q', '-p', 'no:cacheprovider',
                                 '--junitxml', str(report), *TESTS], cwd=ROOT)
        if result.returncode:
            return result.returncode
        print(f'SMS UI gate: {verify_report(report)} passed, zero skipped (real SMS and GG HTTP/browser workflows)', flush=True)
        return 0
    except (ValueError, OSError, subprocess.TimeoutExpired) as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
