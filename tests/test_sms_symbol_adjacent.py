"""Adjacent and legacy sources require geometry before they can influence discovery."""
import hashlib
import json
from pathlib import Path

import pytest

from decompnet.app.engine import RomNetwork
from decompnet.rom import sms, sms_asm, sms_trace
from .test_sms_symbol_import import project as fixture_project
from .test_export_sms import exported as fixture_exported

project, exported = fixture_project, fixture_exported
pytestmark = pytest.mark.skipif(not sms_asm.available(), reason='needs pinned WLA-DX')


@pytest.mark.parametrize('mode', ['declared', 'missing', 'malformed', 'different_revision', 'invalid_geometry', 'null', 'new_version', 'wrong_crc', 'oversized', 'bad_source', 'future_symbols'])
def test_initial_sidecar_import_preserves_bytes_and_never_guesses_nonuniform_geometry(project, tmp_path, mode, monkeypatch):
    _net, slug, image, raw, layout = project
    incoming = tmp_path / 'incoming'; incoming.mkdir()
    path = incoming / ('authored.gg' if slug.endswith('gg') else 'authored.sms')
    # Use the fixture's actual platform rather than its generated project slug.
    platform = _net.cfg(_net.project_row(slug))['platform']
    path = path.with_suffix('.' + platform)
    path.write_bytes(image)
    if mode == 'wrong_crc':
        raw = raw[:raw.index(b'[rom checksum]')] + b'[rom checksum]\n00000000\n'
    elif mode == 'bad_source':
        raw = b'[information]\nversion 1\nversion 2\n[labels]\n01:2100 BrokenMetadata\n'
    elif mode == 'future_symbols':
        raw = raw.replace(b'version 3', b'version 4')
    path.with_suffix('.sym').write_bytes(raw)
    declaration = json.loads(json.dumps(layout))
    if mode == 'different_revision': declaration['input']['sha256'] = '0' * 64
    elif mode == 'invalid_geometry': declaration['banks'][1]['offset'] += 1
    elif mode == 'new_version': declaration['version'] = 2
    if mode == 'oversized':
        from decompnet.app import sms_symbol_adjacent
        monkeypatch.setattr(sms_symbol_adjacent, 'MAX_LAYOUT', 4)
    if mode != 'missing':
        path.with_suffix('.sym.layout.json').write_text('{' if mode == 'malformed' else 'null' if mode == 'null' else json.dumps(declaration))
    net = RomNetwork(tmp_path / 'adjacent.db', tmp_path / 'adjacent-work')
    slug = net.import_rom(path, confirmed=True, log=lambda *_: None)
    proj = net.project_row(slug)
    cfg = net.cfg(proj)
    stored = (Path(proj['root']) / cfg['rom']['file']).with_suffix('.sym')
    assert stored.read_bytes() == raw and path.with_suffix('.sym').read_bytes() == raw
    metadata = net.symbol_file(slug)
    assert metadata['source']['sha256'] == hashlib.sha256(raw).hexdigest()
    functions = {r['rom_offset']: r for r in net.store.all('SELECT * FROM functions WHERE project_id=?', proj['id'])}
    if mode == 'declared':
        assert metadata['state'] == 'declared' and metadata['alias_count'] == 1
        assert functions[0x2100]['name'] == 'First' and functions[0x6100]['name'] == 'Second'
        assert functions[0x9000]['name'] == 'Paged' and functions[0x9000]['vram'] == 0x1000
    else:
        state = {'wrong_crc': 'input_mismatch', 'bad_source': 'rejected', 'future_symbols': 'unsupported_symbol_version'}.get(mode, 'requires_layout')
        assert metadata['state'] == state
        assert metadata['seeds'] == metadata['names'] == 0
        assert not any(r['name'] in ('First', 'FirstAlias', 'Second', 'Paged') for r in functions.values())
        net.resplit_banked(slug, apply=True, log=lambda *_: None)
    assert not metadata['semantic_approval']


def test_undeclared_legacy_and_direct_split_sources_do_not_supply_names_or_seeds(project):
    net, slug, image, raw, layout = project
    proj = net.project_row(slug)
    path = Path(proj['root']) / net.cfg(proj)['rom']['file']
    path.with_suffix('.sym').write_bytes(raw)
    net._update_cfg(slug, lambda cfg: cfg.update(symbol_file={'from': 'legacy.sym', 'at': 0}))
    metadata = net.symbol_file(slug)
    assert metadata['state'] == 'requires_layout' and metadata['names'] == metadata['seeds'] == 0
    inspected = net.inspect_symbols(slug)
    assert inspected['record_count'] and all(r['status'] == 'requires_layout' for r in inspected['records'])
    report = {}
    functions = sms.split(path, path.parent, report=report)
    assert report['symbol_import']['state'] == 'requires_layout'
    assert not any(f.name == 'First' for f in functions)
    normalized = sms_trace.read_sym(raw.decode(), layout=layout, image=image)
    assert normalized[(0, 0x2100)] == 'First'
    assert normalized[(2, 0x1100)] == 'OtherAt1100'


def test_legacy_layout_uncertainty_preserves_actual_accepted_source_and_recovery(exported):
    net, slug, _result, _out = exported
    proj = net.project_row(slug)
    path = net._sym_path(proj)
    raw = b'[labels]\n00:0200 UnqualifiedAlternative\n'
    path.write_bytes(raw)
    net._update_cfg(slug, lambda cfg: cfg.update(symbol_file={'from': 'legacy.sym', 'at': 0}))
    before = dict(net._function('ShowMenu', slug))
    result = net.resplit_banked(slug, apply=True, log=lambda *_: None)
    assert result['symbol_source']['state'] == 'requires_layout'
    assert result['symbol_source']['source']['sha256'] == hashlib.sha256(raw).hexdigest()
    after = net._function('ShowMenu', slug)
    assert after['matched_source'] == before['matched_source'] and after['status'] == 'documented'
    net.undo_resplit(slug, result['history_id'])
    assert net._function('ShowMenu', slug)['matched_source'] == before['matched_source']
    assert path.read_bytes() == raw and net.symbol_file(slug)['state'] == 'requires_layout'


def test_stored_inspection_cannot_mix_mapper_contexts_with_the_same_source_bytes(project):
    from decompnet.network import NetworkError

    net, slug, _image, raw, layout = project
    raw += b'\n[labels]\n' + b'\n'.join(f'01:2100 Alias_{n}'.encode() for n in range(70))
    net.import_symbols(slug, raw.decode(), 'source.sym', layout=layout)
    first = net.inspect_symbols(slug)
    assert first['next_offset'] == 50
    net.sms.configure(slug, 'mapperless', 'annotated-original', 'The authored comparison declares flat cartridge wiring.')
    with pytest.raises(NetworkError, match='context changed'):
        net.inspect_symbols(slug, offset=50, expected_source=first['source_id'], expected_context=first['inspection_context'])
    fresh = net.inspect_symbols(slug)
    assert fresh['source_id'] == first['source_id'] and fresh['inspection_context'] != first['inspection_context']
    assert fresh['seeds'] < first['seeds']  # Paged slot-zero coordinates are impossible on mapperless wiring.
    with pytest.raises(NetworkError, match='source and context'):
        net.inspect_symbols(slug, offset=50, expected_source=fresh['source_id'])


def test_bundle_storage_stays_bound_to_project_root_when_the_input_is_in_a_subfolder(project):
    net, slug, _image, raw, layout = project
    proj = net.project_row(slug)
    root = Path(proj['root'])
    old = root / net.cfg(proj)['rom']['file']
    (root / 'input').mkdir()
    old.rename(root / 'input' / old.name)
    net._update_cfg(slug, lambda cfg: cfg['rom'].update(file='input/' + old.name, program='input/' + old.name))
    net.import_symbols(slug, raw.decode(), 'source.sym', layout=layout)
    assert net.inspect_symbols(slug)['state'] == 'declared'
    result = net.resplit_banked(slug, apply=True, log=lambda *_: None)
    assert result['symbol_source']['state'] == 'declared'
    assert net._function('First', slug)['rom_offset'] == 0x2100
    assert (root / '.symbol-imports').is_dir() and not (root / 'input' / '.symbol-imports').exists()
