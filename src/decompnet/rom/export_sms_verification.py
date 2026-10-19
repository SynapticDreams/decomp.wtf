"""Independently verify a standalone build receipt and its actual output; stdout is diagnostic only."""
import json

from .export_sms_report import identity
from .export_sms_artifacts import read_regular

MAX_REPORT = 16 * 1024 * 1024


def verify(out, image, expected, returncode, platform, *, required=False):
    errors, report, receipt_valid = [], None, False
    measured_input, measured_image = {'verified': False}, {'checked': False, 'equal': None}
    built = None
    try:
        if (out / 'build').is_symlink():
            raise ValueError('verification_output_directory_is_a_symlink')
        built, info = read_regular(out / 'build' / f'game.{platform}', len(image) + 1)
        equal = built == image
        measured_image = {'checked': True, 'equal': equal, 'original': identity(image),
                          'built': identity(built) if info.st_size == len(built) else {'size': info.st_size, 'sha256': None},
                          'first_difference': next((i for i, (a, b) in enumerate(zip(image, built)) if a != b),
                                                   min(len(image), len(built))) if not equal else None}
    except (OSError, ValueError):
        errors.append('output_artifact_unavailable_or_changed')
    try:
        if (out / 'build').is_symlink():
            raise ValueError('verification_output_directory_is_a_symlink')
        path = out / 'build' / 'verification.json'
        raw, _info = read_regular(path, MAX_REPORT + 1)
        if len(raw) > MAX_REPORT:
            raise ValueError('verification_report_too_large')
        report = json.loads(raw.decode('utf-8'))
        if type(report.get('version')) is not int or report['version'] != 1:
            raise ValueError('unsupported_verification_report')
        if report['input'].get('verified') is not True or report['input'].get('normalized') != identity(image):
            raise ValueError('input_verification_missing_or_different')
        measured_input = {'verified': True, 'normalized': identity(image)}
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
        if built is None:
            raise ValueError('output_artifact_was_not_measured')
        if report['image'].get('built') != identity(built) or report['image'].get('original') != identity(image):
            raise ValueError('output_artifact_differs_from_receipt')
        equal = measured_image['equal']
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
            'input': measured_input, 'image': measured_image,
            'build': report if isinstance(report, dict) else None,
            'scope': 'independent input/output artifact and process check; source receipt is build-reported'}
