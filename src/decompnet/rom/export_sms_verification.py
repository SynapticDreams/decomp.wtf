"""Independently verify a standalone build receipt and its actual output; stdout is diagnostic only."""
import json

from .export_sms_report import identity

MAX_REPORT = 16 * 1024 * 1024


def verify(out, image, expected, returncode, platform, *, required=False):
    errors, report, receipt_valid = [], None, False
    try:
        path = out / 'build' / 'verification.json'
        with path.open('rb') as stream:
            raw = stream.read(MAX_REPORT + 1)
        if len(raw) > MAX_REPORT:
            raise ValueError('verification_report_too_large')
        report = json.loads(raw.decode('utf-8'))
        if type(report.get('version')) is not int or report['version'] != 1:
            raise ValueError('unsupported_verification_report')
        if report['input'].get('verified') is not True or report['input'].get('normalized') != identity(image):
            raise ValueError('input_verification_missing_or_different')
        rows = report['documented']['routines']
        if not isinstance(rows, list) or len(rows) != len(expected):
            raise ValueError('documented_receipt_count_differs')
        for row, entry in zip(rows, expected):
            if any(row.get(key) != entry.get(key) for key in ('name', 'flat', 'cpu', 'size', 'source_sha256')):
                raise ValueError('documented_receipt_identity_differs')
            if type(row.get('emitted')) is not bool or type(row.get('inserted')) is not bool:
                raise ValueError('invalid_documented_receipt')
            if row['inserted'] and not row['emitted']:
                raise ValueError('inserted_source_was_not_emitted')
            if row['inserted'] and row.get('actual_source_sha256') != entry.get('source_sha256'):
                raise ValueError('documented_source_changed')
            if not row['inserted'] and not isinstance(row.get('omission'), str):
                raise ValueError('omitted_source_has_no_reason')
        with (out / 'build' / f'game.{platform}').open('rb') as stream:
            built = stream.read(len(image) + 1)
        if report['image'].get('built') != identity(built) or report['image'].get('original') != identity(image):
            raise ValueError('output_artifact_differs_from_receipt')
        equal = built == image
        if report['image'].get('equal') is not equal:
            raise ValueError('image_equality_receipt_differs')
        if report['process'].get('completed') is not True:
            raise ValueError('build_process_incomplete')
        if type(report['process'].get('exit_code')) is not int or report['process']['exit_code'] != returncode:
            raise ValueError('build_process_status_differs')
        if report['documented'].get('required') is not required:
            raise ValueError('source_insertion_policy_differs')
        expected_pass = equal and not (required and any(not row['inserted'] for row in rows))
        if type(report.get('passed')) is not bool or report['passed'] is not expected_pass:
            raise ValueError('build_policy_status_differs')
        receipt_valid = True
        if not equal:
            errors.append('image_differs')
        if required and any(not row['inserted'] for row in rows):
            errors.append('required_documented_source_omitted')
    except (OSError, UnicodeError, ValueError, KeyError, TypeError, AttributeError) as exc:
        errors.append(str(exc) if isinstance(exc, ValueError) and not isinstance(exc, json.JSONDecodeError) else
                      'verification_report_or_artifact_unavailable')
    if returncode != 0:
        errors.append('build_process_failed')
    passed = not errors
    return {'version': 1, 'passed': passed, 'receipt_valid': receipt_valid, 'errors': errors,
            'build': report if isinstance(report, dict) else None,
            'scope': 'independent input/output artifact and process check; source receipt is build-reported'}
