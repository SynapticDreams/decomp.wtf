"""Declared project sources are inspectable, revision-bound and safe across resplit recovery."""
import base64
import json
from pathlib import Path
import sqlite3
import subprocess

import pytest

from decompnet.app.engine import RomNetwork
from decompnet.network import NetworkError
from decompnet.rom import sms_asm, wla_bundle
from .sms_wla_fixture import SOURCE, layout_for

pytestmark = pytest.mark.skipif(not sms_asm.available(), reason='needs pinned WLA-DX')


@pytest.fixture(params=['sms', 'gg'])
def project(tmp_path, request):
    assembler, linker = sms_asm._tools()
    (tmp_path / 'game.asm').write_text(SOURCE)
    (tmp_path / 'link').write_text('[objects]\ngame.o\n')
    for args in ([str(assembler), '-i', '-o', 'game.o', 'game.asm'],
                 [str(linker), '-S', '-A', 'link', f'game.{request.param}']):
        run = subprocess.run(args, cwd=tmp_path, capture_output=True, text=True, timeout=30)
        assert run.returncode == 0, run.stdout + run.stderr
    path = tmp_path / f'game.{request.param}'
    image = path.read_bytes()
    raw = path.with_suffix('.sym').read_bytes()
    path.with_suffix('.sym').unlink()  # Start without a historical physical-bank symbol assumption.
    net = RomNetwork(tmp_path / 'work.db', tmp_path / 'work')
    slug = net.import_rom(path, confirmed=True, log=lambda *_: None)
    net.sms.configure(slug, 'sega', 'annotated-original', 'The authored fixture specifies Sega cartridge mapping.')
    return net, slug, image, raw, layout_for(image)


def rows(net, slug):
    return [dict(r) for r in net.store.all('SELECT * FROM functions WHERE project_id=? ORDER BY id', net.project_row(slug)['id'])]


def test_preview_apply_reload_resplit_and_undo_preserve_source_identity_and_existing_work(project):
    net, slug, image, raw, layout = project
    proj = net.project_row(slug)
    root = Path(proj['root'])
    before, cfg = rows(net, slug), net.cfg(proj)
    preview = net.import_symbols(slug, '', 'fixture.sym', layout=layout, apply=False,
                                 source_base64=base64.b64encode(raw).decode())
    assert not preview['applied'] and preview['renamed'] == 0
    assert net.cfg(net.project_row(slug)) == cfg and rows(net, slug) == before
    assert not (root / '.symbol-imports').exists()
    applied = net.import_symbols(slug, '', 'fixture.sym', layout=layout, expected_plan=preview['plan'],
                                 source_base64=base64.b64encode(raw).decode())
    assert applied['applied'] and rows(net, slug) == before
    reference = net.cfg(net.project_row(slug))['symbol_file']
    loaded = wla_bundle.load(root, reference, image)
    assert loaded.report['source'] == preview['symbol_file']['source']
    assert base64.b64decode(json.loads(loaded.payload)['source']) == raw
    assert net.symbol_file(slug)['alias_count'] == 1
    assert not net.symbol_file(slug)['semantic_approval']
    result = net.resplit_banked(slug, apply=True, log=lambda *_: None)
    found = {r['rom_offset']: r for r in rows(net, slug)}
    assert found[0x2100]['name'] == 'First' and found[0x6100]['name'] == 'Second'
    assert found[0x9000]['name'] == 'Paged' and found[0x9000]['vram'] == 0x1000
    assert found[0x1100]['name'] == 'MainAt1100' and found[0x9100]['name'] == 'OtherAt1100'
    net.undo_resplit(slug, result['history_id'])
    assert rows(net, slug) == before
    assert net.cfg(net.project_row(slug))['symbol_file'] == reference
    assert wla_bundle.verified(root, reference) == loaded.payload
    reopened = RomNetwork(Path(net.store.one('PRAGMA database_list')['file']), net.workspace)
    assert reopened.symbol_file(slug)['source_id'] == loaded.sha256


def test_missing_layout_retains_raw_records_without_applying_names_or_seeds(project):
    net, slug, _image, raw, _layout = project
    before = rows(net, slug)
    result = net.import_symbols(slug, raw.decode(), 'raw.sym')
    assert result['symbol_file']['state'] == 'requires_layout' and result['renamed'] == 0
    assert result['symbol_file']['names'] == result['symbol_file']['seeds'] == 0
    net.resplit_banked(slug, apply=True, log=lambda *_: None)
    assert rows(net, slug) == before
    assert all(row['status'] == 'requires_layout' for row in net.inspect_symbols(slug)['records'])


def test_inspection_pages_preserve_every_alias_and_reject_a_changed_source(project):
    net, slug, _image, raw, layout = project
    raw += b'\n[labels]\n' + b'\n'.join(f'01:2100 Alias_{n}'.encode() for n in range(130))
    result = net.import_symbols(slug, raw.decode(), 'many.sym', layout=layout)
    source = result['symbol_file']['source_id']
    inspected, offset, context = [], 0, None
    while True:
        page = net.inspect_symbols(slug, offset=offset, expected_source=source, expected_context=context)
        context = page['inspection_context']
        assert len(page['records']) <= 50
        inspected.extend(page['records'])
        if page['next_offset'] is None:
            break
        offset = page['next_offset']
    assert len(inspected) == result['kept'] and len({r['name'] for r in inspected if r['name'].startswith('Alias_')}) == 130
    assert 'game.asm' not in str(page)
    net.import_symbols(slug, raw.decode() + '\n; source change\n', 'many.sym', layout=layout)
    with pytest.raises(NetworkError, match='changed'):
        net.inspect_symbols(slug, offset=50, expected_source=source, expected_context=context)


@pytest.mark.parametrize('change', ['source', 'work', 'input'])
def test_stale_preview_never_replaces_current_source_or_work(project, change):
    net, slug, image, raw, layout = project
    preview = net.import_symbols(slug, raw.decode(), 'source.sym', layout=layout, apply=False)
    if change == 'source':
        net.import_symbols(slug, raw.decode() + '\n; other source', 'other.sym', layout=layout)
    elif change == 'work':
        with net.store.tx() as db:
            db.execute("INSERT INTO notes(project_id,text) VALUES(?,'authored concurrent note')", (net.project_row(slug)['id'],))
    else:
        proj = net.project_row(slug)
        (Path(proj['root']) / net.cfg(proj)['rom']['file']).write_bytes(image[:-1] + b'\0')
    cfg, before = net.cfg(net.project_row(slug)), rows(net, slug)
    with pytest.raises(NetworkError):
        net.import_symbols(slug, raw.decode(), 'source.sym', layout=layout, expected_plan=preview['plan'])
    assert net.cfg(net.project_row(slug)) == cfg and rows(net, slug) == before


def test_corrupt_bundle_is_visible_and_stops_resplit_without_legacy_fallback(project):
    net, slug, _image, raw, layout = project
    net.import_symbols(slug, raw.decode(), 'source.sym', layout=layout)
    proj = net.project_row(slug)
    reference = net.cfg(proj)['symbol_file']
    path = wla_bundle.path(Path(proj['root']), reference)
    path.write_bytes(path.read_bytes() + b' ')
    net._sym_path(proj).write_text('00:0200 DecoyLegacyName\n')
    before = rows(net, slug)
    assert net.symbol_file(slug)['state'] == 'unavailable'
    with pytest.raises(NetworkError, match='source'):
        net.resplit_banked(slug, apply=True, log=lambda *_: None)
    assert rows(net, slug) == before


def test_remove_disables_sources_and_keeps_original_provenance_without_legacy_fallback(project):
    net, slug, _image, raw, layout = project
    net.import_symbols(slug, raw.decode(), 'source.sym', layout=layout)
    proj = net.project_row(slug)
    reference = net.cfg(proj)['symbol_file']
    net._sym_path(proj).write_text('00:0200 DecoyLegacyName\n')
    net.remove_symbol_file(slug)
    assert net.symbol_file(slug) is None
    assert wla_bundle.verified(Path(proj['root']), reference)
    assert net._hints(net.project_row(slug))['symbol_source']['format'] == 'disabled'
    net.resplit_banked(slug, apply=True, log=lambda *_: None)
    assert not any(row['name'] == 'DecoyLegacyName' for row in rows(net, slug))


def test_failed_database_publication_does_not_change_the_active_source_or_functions(project):
    net, slug, _image, raw, layout = project
    net.import_symbols(slug, raw.decode(), 'source.sym', layout=layout)
    cfg, before = net.cfg(net.project_row(slug)), rows(net, slug)
    with net.store.tx() as db:
        db.execute("CREATE TRIGGER authored_failure BEFORE UPDATE ON projects BEGIN SELECT RAISE(ABORT,'authored failure'); END")
    with pytest.raises(sqlite3.IntegrityError, match='authored failure'):
        net.import_symbols(slug, raw.decode() + '\n; changed source', 'different.sym', layout=layout)
    assert net.cfg(net.project_row(slug)) == cfg and rows(net, slug) == before
    assert net.inspect_symbols(slug)['source_id'] == cfg['symbol_file']['bundle_sha256']


def test_new_work_during_preparation_survives_and_prevents_source_application(project, monkeypatch):
    net, slug, _image, raw, layout = project
    original = wla_bundle.prepare
    def prepare(*args, **kwargs):
        result = original(*args, **kwargs)
        with net.store.tx() as db:
            db.execute("INSERT INTO notes(project_id,text) VALUES(?,'authored work during preparation')", (net.project_row(slug)['id'],))
        return result
    monkeypatch.setattr(wla_bundle, 'prepare', prepare)
    with pytest.raises(NetworkError, match='changed during symbol import'):
        net.import_symbols(slug, raw.decode(), 'source.sym', layout=layout)
    assert net.store.one("SELECT 1 FROM notes WHERE text='authored work during preparation'")
    assert 'symbol_file' not in net.cfg(net.project_row(slug))
    assert not (Path(net.project_row(slug)['root']) / '.symbol-imports').exists()


def test_bundle_change_after_resplit_blocks_undo_and_preserves_current_work(project):
    net, slug, _image, raw, layout = project
    net.import_symbols(slug, raw.decode(), 'source.sym', layout=layout)
    result = net.resplit_banked(slug, apply=True, log=lambda *_: None)
    proj = net.project_row(slug)
    reference = net.cfg(proj)['symbol_file']
    path = wla_bundle.path(Path(proj['root']), reference)
    path.write_bytes(path.read_bytes() + b' ')
    before = rows(net, slug)
    with pytest.raises(NetworkError, match='symbol source'):
        net.undo_resplit(slug, result['history_id'])
    assert rows(net, slug) == before


@pytest.mark.parametrize('reference', [[], False, {'format': 'wla-bundle', 'version': 2, 'bundle_sha256': '0' * 64}])
def test_invalid_or_newer_source_metadata_never_reactivates_legacy_symbols(project, reference):
    net, slug, _image, _raw, _layout = project
    net._sym_path(net.project_row(slug)).write_text('00:0200 DecoyLegacyName\n')
    net._update_cfg(slug, lambda cfg: cfg.update(symbol_file=reference))
    before = rows(net, slug)
    assert net.symbol_file(slug)['state'] == 'unavailable'
    with pytest.raises(NetworkError):
        net.resplit_banked(slug, apply=True, log=lambda *_: None)
    assert rows(net, slug) == before


def test_room_members_can_inspect_their_source_but_cannot_replace_or_disable_it(project):
    net, slug, _image, raw, layout = project
    net.import_symbols(slug, raw.decode(), 'source.sym', layout=layout)
    net.links[slug] = {}  # Authored room membership; no external service is contacted.
    assert net.symbol_file(slug)['state'] == 'declared'
    assert net.inspect_symbols(slug)['records']
    with pytest.raises(NetworkError, match='local SMS/GG'):
        net.import_symbols(slug, raw.decode(), 'other.sym', layout=layout)
    with pytest.raises(NetworkError, match='local SMS/GG'):
        net.remove_symbol_file(slug)
