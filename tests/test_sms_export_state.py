"""Export state stays bounded, historical when work changes, and separate from current input readiness."""
import json
from pathlib import Path

import pytest

from decompnet.app.sms_export_state import summary
from decompnet.rom import sms_asm

from .test_export_sms import exported as fixture_exported

exported = fixture_exported
pytestmark = pytest.mark.skipif(not sms_asm.available(), reason='needs WLA-DX')


@pytest.mark.parametrize('change', ['source', 'header', 'symbol', 'note', 'profile', 'input', 'missing',
                                     'tree', 'artifact', 'receipt', 'baserom', 'tree_missing'])
def test_last_success_is_historical_after_work_or_input_changes(exported, change):
    net, slug, result, out = exported
    before = net.overview(slug)
    assert before['export']['current'] and before['export']['identical']
    assert before['export']['verification']['documented']['inserted'] == 1
    proj = net.project_row(slug)
    if change in ('missing', 'input'):
        image = Path(proj['root']) / net.cfg(proj)['rom']['file']
        if change == 'missing':
            image.unlink()
        else:
            changed = bytearray(image.read_bytes()); changed[512] ^= 1; image.write_bytes(changed)
    elif change == 'profile':
        net._update_cfg(slug, lambda cfg: cfg['sms_profile'].update(reason='Different authored project evidence for comparison.'))
    elif change in ('tree', 'artifact', 'receipt', 'baserom', 'tree_missing'):
        platform = net.cfg(proj)['platform']
        if change == 'tree':
            path = out / 'documented' / 'ShowMenu.asm'
            path.write_text(path.read_text() + '; authored tree edit\n')
        elif change == 'tree_missing':
            (out / 'tools' / 'z80.py').unlink()
        else:
            path = out / ('build/verification.json' if change == 'receipt' else f'build/game.{platform}' if change == 'artifact' else f'baserom.{platform}')
            path.write_bytes(path.read_bytes() + b'changed')
    else:
        with net.store.tx() as db:
            if change == 'source':
                db.execute("UPDATE functions SET matched_source=matched_source||'; authored edit' WHERE project_id=? AND status='documented'", (proj['id'],))
            elif change == 'header':
                db.execute("UPDATE context_versions SET header=header||'\n/* authored edit */' WHERE project_id=?", (proj['id'],))
            elif change == 'symbol':
                db.execute("UPDATE symbols SET address=address+1 WHERE project_id=? AND name='wMenuOpen'", (proj['id'],))
            else:
                db.execute("INSERT INTO notes(project_id,text) VALUES(?,'New authored observation')", (proj['id'],))
    after = net.overview(slug)
    assert not after['export']['current'] and not after['export']['identical']
    assert after['export']['historical_identical'] and after['export']['verification']['image']['equal']
    assert after['sms_progress']['input']['status'] == ('missing' if change == 'missing' else 'different' if change == 'input' else 'verified')
    assert result['verification']['passed']  # The earlier measured result remains a historical fact.


def test_tree_edit_during_the_build_cannot_bind_a_current_success(exported, monkeypatch):
    from decompnet.rom import export_sms

    net, slug, _result, out = exported
    original = export_sms.subprocess.run
    def run(args, **kwargs):
        result = original(args, **kwargs)
        if 'build.py' in args:
            path = out / 'documented' / 'ShowMenu.asm'
            path.write_text(path.read_text() + '; new authored change\n')
        return result
    monkeypatch.setattr(export_sms.subprocess, 'run', run)
    result = net.export_rom(slug)
    assert result['verification']['build']['image']['equal']
    assert not result['verification']['export_inputs_coherent'] and not result['identical']
    assert 'export_inputs_changed_or_unavailable' in result['verification']['errors']
    assert not net.overview(slug)['export']['current']


def test_result_edit_after_measurement_cannot_be_bound_to_the_older_success(exported, monkeypatch):
    from decompnet.rom import export_sms

    net, slug, _result, out = exported
    original = export_sms.verify
    def verify(*args, **kwargs):
        checked = original(*args, **kwargs)
        platform = net.cfg(net.project_row(slug))['platform']
        (out / 'build' / f'game.{platform}').write_bytes(b'changed after measurement')
        return checked
    monkeypatch.setattr(export_sms, 'verify', verify)
    result = net.export_rom(slug)
    assert result['verification']['image']['equal'] and not result['verification']['export_outputs_coherent']
    assert not result['identical'] and 'export_results_changed_or_unavailable' in result['verification']['errors']
    assert not net.overview(slug)['export']['current']


def test_failed_preflight_records_a_new_failed_attempt_and_keeps_previous_output(exported):
    net, slug, _result, out = exported
    proj = net.project_row(slug)
    original = (out / 'build' / f'game.{net.cfg(proj)["platform"]}').read_bytes()
    (Path(proj['root']) / net.cfg(proj)['rom']['file']).unlink()
    with pytest.raises(OSError):
        net.export_rom(slug, strict_documented=True)
    state = net.overview(slug)
    assert not state['export']['identical'] and not state['export']['verification']['passed']
    assert state['export']['verification']['process']['stage'] == 'export'
    assert state['export']['verification']['documented']['required']
    assert (out / 'build' / f'game.{net.cfg(proj)["platform"]}').read_bytes() == original


def test_unbound_legacy_input_cannot_be_promoted_to_an_exact_export(exported):
    net, slug, _result, out = exported
    build = (out / 'build.json').read_bytes()
    def unbind(cfg):
        cfg['rom'].pop('identity', None)
        cfg['rom'].pop('sha1', None)
    net._update_cfg(slug, unbind)
    assert net.overview(slug)['sms_progress']['input']['status'] == 'unbound'
    with pytest.raises(ValueError, match='declare a profile'):
        net.export_rom(slug)
    assert (out / 'build.json').read_bytes() == build
    assert not net.overview(slug)['export']['identical']


def test_summary_counts_union_inserted_bytes_and_bounds_omission_bodies(exported):
    _net, _slug, result, _out = exported
    verification = json.loads(json.dumps(result['verification']))
    rows = verification['build']['documented']['routines']
    rows.extend([dict(rows[0]), *[dict(rows[0], name='x' * 1000, inserted=False, omission='why' * 1000) for _ in range(120)]])
    saved = summary(verification, 'fixture', True)
    assert saved['documented']['inserted'] == 2 and saved['documented']['inserted_bytes'] == rows[0]['size']
    assert len(saved['documented']['omissions']) == 100 and saved['documented']['omissions_truncated']
    assert len(saved['documented']['omissions'][0]['name']) == 512
    assert 'routines' not in saved['documented'] and len(json.dumps(saved)) < 120000


def test_new_work_during_export_remains_and_prevents_a_current_success_claim(exported, monkeypatch):
    from decompnet.rom import export_sms

    net, slug, _result, _out = exported
    original = export_sms.subprocess.run
    def run(args, **kwargs):
        result = original(args, **kwargs)
        if 'build.py' in args:
            with net.store.tx() as db:
                db.execute('INSERT INTO notes(project_id,text) VALUES(?,?)', (net.project_row(slug)['id'], 'Concurrent authored observation'))
        return result
    monkeypatch.setattr(export_sms.subprocess, 'run', run)
    result = net.export_rom(slug)
    assert result['verification']['passed']
    state = net.overview(slug)
    assert not state['export']['current'] and not state['export']['identical']
    assert not state['export']['verification']['coherent']
    assert net.store.one("SELECT 1 FROM notes WHERE text='Concurrent authored observation'")
