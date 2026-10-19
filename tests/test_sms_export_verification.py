"""Structured receipts, actual artifacts and process status determine export verification."""
import json
import subprocess
import sys
from types import SimpleNamespace

import pytest

from decompnet.rom import export_sms as exporter, sms_asm
from decompnet.rom.export_sms_report import Report
from decompnet.rom.export_sms_verification import verify

from .test_export_sms import exported as fixture_exported

exported = fixture_exported
tools = pytest.mark.skipif(not sms_asm.available(), reason='needs pinned WLA-DX')


def receipt(tmp_path):
    config = {'sha1': 'authored', 'platform': 'sms'}
    report = Report(tmp_path, config, {'documented': []}, [])
    report.input(b'authored')
    assert report.complete(b'authored', b'authored') == 0
    (tmp_path / 'build' / 'game.sms').write_bytes(b'authored')
    report.write()
    return report


@pytest.mark.parametrize('change', ['missing_report', 'malformed', 'list', 'missing_artifact', 'artifact_changed',
    'input_changed', 'incomplete', 'false_equality', 'status', 'policy', 'rows', 'false_passed'])
def test_bad_or_missing_verification_evidence_never_passes(tmp_path, change):
    report = receipt(tmp_path)
    if change == 'missing_report':
        report.path.unlink()
    elif change == 'malformed':
        report.path.write_text('invalid')
    elif change == 'list':
        report.path.write_text('[]')
    elif change == 'missing_artifact':
        (tmp_path / 'build' / 'game.sms').unlink()
    elif change == 'artifact_changed':
        (tmp_path / 'build' / 'game.sms').write_bytes(b'changed')
    else:
        if change == 'input_changed':
            report.value['input']['verified'] = False
        elif change == 'incomplete':
            report.value['process']['completed'] = False
        elif change == 'false_equality':
            report.value['image']['equal'] = False
        elif change == 'status':
            report.value['process']['exit_code'] = 1
        elif change == 'policy':
            report.value['documented']['required'] = True
        elif change == 'false_passed':
            report.value['passed'] = False
        else:
            report.value['documented']['routines'] = ['wrong']
        report.write()
    assert not verify(tmp_path, b'authored', [], 0, 'sms')['passed']


def test_process_failure_cannot_be_hidden_by_matching_artifacts(tmp_path):
    receipt(tmp_path)
    assert verify(tmp_path, b'authored', [], 0, 'sms')['passed']
    result = verify(tmp_path, b'authored', [], 1, 'sms')
    assert not result['passed'] and 'build_process_failed' in result['errors']


@tools
def test_standalone_reports_inserted_disabled_and_required_source_separately(exported):
    net, slug, result, out = exported
    assert result['verification']['passed'] and result['verification']['build']['documented']['routines'][0]['inserted']
    expected = json.loads((out / 'build.json').read_text())['expected_documented']
    platform = net.cfg(net.project_row(slug))['platform']
    image = (out / f'baserom.{platform}').read_bytes()
    for strict in (False, True):
        args = [sys.executable, 'build.py', '--no-documented', *(['--require-documented'] if strict else [])]
        proc = subprocess.run(args, cwd=out, capture_output=True, text=True, timeout=30)
        report = json.loads((out / 'build' / 'verification.json').read_text())
        assert report['input']['verified'] and report['image']['equal']
        row = report['documented']['routines'][0]
        assert not row['inserted'] and row['omission'] == 'disabled_by_option'
        assert proc.returncode == int(strict) and report['passed'] is not strict
        assert verify(out, image, expected, proc.returncode, platform, required=strict)['passed'] is not strict


@tools
def test_export_does_not_trust_a_success_word_without_new_artifacts(exported, monkeypatch):
    net, slug, _result, _out = exported
    original = exporter.subprocess.run
    def run(args, **kwargs):
        if 'build.py' in args:
            return SimpleNamespace(returncode=0, stdout='identical, everything passed', stderr='')
        return original(args, **kwargs)
    monkeypatch.setattr(exporter.subprocess, 'run', run)
    result = net.export_rom(slug, log=lambda *_: None)
    assert not result['identical'] and result['documented'] == 0
    assert result['left_out'] == [('ShowMenu', 'source_insertion_unverified')]


@tools
def test_preflight_omission_remains_visible_even_when_raw_reconstruction_passes(exported, monkeypatch):
    net, slug, _result, out = exported
    monkeypatch.setattr(exporter, '_documented', lambda *args, **kwargs: ([], [('ShowMenu', 'authored preflight failure')]))
    for strict in (False, True):
        result = exporter.export_sms(net, slug, out, log=lambda *_: None, strict_documented=strict)
        assert result['verification']['build']['image']['equal'] and result['identical'] is not strict
        assert result['documented'] == 0 and result['left_out'] == [('ShowMenu', 'authored preflight failure')]


@tools
def test_changed_assembly_reports_actual_insertion_and_the_image_difference(exported):
    _net, _slug, _result, out = exported
    source = out / 'documented' / 'ShowMenu.asm'
    source.write_text(source.read_text().replace('ld a, $81', 'ld a, $82'))
    proc = subprocess.run([sys.executable, 'build.py'], cwd=out, capture_output=True, text=True, timeout=30)
    report = json.loads((out / 'build' / 'verification.json').read_text())
    assert proc.returncode == 1 and not report['passed'] and not report['image']['equal']
    assert report['image']['first_difference'] == 0x206
    row = report['documented']['routines'][0]
    assert row['inserted'] and row['source_sha256'] != row['actual_source_sha256']


@tools
def test_stored_crlf_source_and_emitted_text_use_the_same_declared_hash_normalization(exported):
    net, slug, _result, _out = exported
    with net.store.tx() as db:
        db.execute("UPDATE functions SET matched_source=replace(matched_source,char(10),char(13)||char(10)) "
                   "WHERE project_id=? AND name='ShowMenu'", (net.project_row(slug)['id'],))
    result = net.export_rom(slug, log=lambda *_: None)
    assert result['identical'], result['verification']
    doc = result['verification']['build']['documented']
    row = doc['routines'][0]
    assert row['inserted'] and row['source_sha256'] == row['actual_source_sha256']
    assert 'universal newlines' in doc['source_hash_scope']


@tools
@pytest.mark.parametrize('failure', ['missing', 'wrong', 'tool'])
def test_failed_standalone_run_replaces_old_success_receipts_and_artifacts(exported, failure):
    net, slug, _result, out = exported
    platform = net.cfg(net.project_row(slug))['platform']
    image = out / f'baserom.{platform}'
    if failure == 'missing':
        image.unlink()
    elif failure == 'wrong':
        image.write_bytes(b'wrong input')
    else:
        # A real child process fails on the assembler arguments on every host platform.
        script = out / 'build.py'
        source = script.read_text()
        start, end = source.index('def tools()'), source.index('def run(')
        source = source[:start] + 'def tools():\n    return Path(sys.executable), Path(sys.executable)\n\n\n' + source[end:]
        script.write_text(source)
    proc = subprocess.run([sys.executable, 'build.py'], cwd=out, capture_output=True, text=True, timeout=30)
    report = json.loads((out / 'build' / 'verification.json').read_text())
    assert proc.returncode != 0 and not report['passed'] and not report['image']['equal']
    assert not (out / 'build' / f'game.{platform}').exists()
    assert report['process']['stage'] == ('assemble' if failure == 'tool' else 'input')
