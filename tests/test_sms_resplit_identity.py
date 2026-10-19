"""Resplitting must not commit discovery for a changed revision or stale mapper declaration."""
from pathlib import Path

import pytest

from decompnet.app.engine import RomNetwork
from decompnet.network import NetworkError
from decompnet.rom import sms

from .test_sms import make_rom

REASON = 'The authored fixture declares its cartridge selector wiring.'


@pytest.fixture
def project(tmp_path):
    net = RomNetwork(tmp_path / 'state.db', tmp_path / 'projects')
    net.auto_install_tools = False
    slug = net.import_rom(make_rom(code={0: bytes.fromhex('cd0002 18fe'), 0x200: b'\xc9'}),
                          name='fixture.sms', confirmed=True, log=lambda *_: None)
    proj = net.project_row(slug)
    path = Path(proj['root']) / net.cfg(proj)['rom']['file']
    return net, slug, path


def rows(net, slug):
    pid = net.project_row(slug)['id']
    return [dict(row) for row in net.store.all('SELECT * FROM functions WHERE project_id=? ORDER BY id', pid)]


def change(path):
    data = bytearray(path.read_bytes())
    data[0x201] ^= 1
    path.write_bytes(data)


@pytest.mark.parametrize('apply', [False, True])
def test_changed_revision_is_rejected_before_discovery_without_changing_work(project, monkeypatch, apply):
    net, slug, path = project
    before, cfg = rows(net, slug), net.cfg(net.project_row(slug))
    change(path)
    calls = []
    monkeypatch.setattr(sms, 'split', lambda *_a, **_k: calls.append(True) or [])
    with pytest.raises(NetworkError, match='resplit.*input'):
        net.resplit_banked(slug, apply=apply, log=lambda *_: None)
    assert not calls and rows(net, slug) == before and net.cfg(net.project_row(slug)) == cfg


@pytest.mark.parametrize('apply', [False, True])
def test_input_changed_during_discovery_cannot_replace_function_rows(project, monkeypatch, apply):
    net, slug, path = project
    before, cfg = rows(net, slug), net.cfg(net.project_row(slug))
    original = sms.split

    def split(*args, **kwargs):
        result = original(*args, **kwargs)
        change(path)
        return result

    monkeypatch.setattr(sms, 'split', split)
    with pytest.raises(NetworkError, match='resplit.*input'):
        net.resplit_banked(slug, apply=apply, log=lambda *_: None)
    assert rows(net, slug) == before and net.cfg(net.project_row(slug)) == cfg


@pytest.mark.parametrize('apply', [False, True])
def test_profile_changed_during_discovery_cannot_apply_or_preview_the_old_model(project, monkeypatch, apply):
    net, slug, _path = project
    net.sms.configure(slug, 'sega', 'annotated-original', REASON)
    before = rows(net, slug)
    original = sms.split

    def split(*args, **kwargs):
        result = original(*args, **kwargs)
        net.sms.configure(slug, 'codemasters', 'annotated-original', REASON)
        return result

    monkeypatch.setattr(sms, 'split', split)
    with pytest.raises(NetworkError, match='mapping or ROM metadata changed'):
        net.resplit_banked(slug, apply=apply, log=lambda *_: None)
    assert rows(net, slug) == before
    assert net.sms.inspect(slug)['profile']['mapper'] == 'codemasters'  # retain the concurrent edit


def test_equivalent_copier_wrapper_and_legacy_identity_remain_usable(project):
    net, slug, path = project
    before = rows(net, slug)
    path.write_bytes(b'\0' * 512 + path.read_bytes())
    preview = net.resplit_banked(slug, log=lambda *_: None)
    assert preview['kept'] == preview['before'] and rows(net, slug) == before
    net._update_cfg(slug, lambda cfg: cfg['rom'].pop('identity'))
    assert net.resplit_banked(slug, log=lambda *_: None)['kept'] == len(before)
    change(path)
    with pytest.raises(NetworkError, match='resplit.*input'):
        net.resplit_banked(slug, log=lambda *_: None)


def test_input_changed_during_database_updates_rolls_back_the_apply(project, monkeypatch):
    net, slug, path = project
    before, cfg = rows(net, slug), net.cfg(net.project_row(slug))
    pid = net.project_row(slug)['id']
    regions = [dict(r) for r in net.store.all('SELECT * FROM data_regions WHERE project_id=? ORDER BY rom_offset', pid)]
    original = net._store_regions

    def store_regions(db, project_id, new_regions):
        # Make a visible interpretation change before the input changes, so merely raising
        # an error after a committed update cannot satisfy the rollback assertion.
        original(db, project_id, [*new_regions, (0x201, 1, 'data', 'Fixture interpretation changed')])
        change(path)

    monkeypatch.setattr(net, '_store_regions', store_regions)
    with pytest.raises(NetworkError, match='resplit.*input'):
        net.resplit_banked(slug, apply=True, log=lambda *_: None)
    assert rows(net, slug) == before and net.cfg(net.project_row(slug)) == cfg
    assert [dict(r) for r in net.store.all(
        'SELECT * FROM data_regions WHERE project_id=? ORDER BY rom_offset', pid)] == regions


@pytest.mark.parametrize('identity', [None, 'invalid'])
def test_missing_or_malformed_frozen_identity_cannot_claim_revision_validation(project, identity):
    net, slug, _path = project

    def erase(cfg):
        cfg['rom']['identity'] = identity
        cfg['rom'].pop('sha1', None)

    net._update_cfg(slug, erase)
    before, cfg = rows(net, slug), net.cfg(net.project_row(slug))
    with pytest.raises(NetworkError, match='resplit.*input'):
        net.resplit_banked(slug, apply=True, log=lambda *_: None)
    assert rows(net, slug) == before and net.cfg(net.project_row(slug)) == cfg


def test_concurrent_compiler_settings_are_not_overwritten_by_resplit(project, monkeypatch):
    net, slug, _path = project
    before = rows(net, slug)
    original = sms.split

    def split(*args, **kwargs):
        result = original(*args, **kwargs)
        net._update_cfg(slug, lambda cfg: cfg['compiler']['flags'].append('-DRETAIN_USER_SETTING'))
        return result

    monkeypatch.setattr(sms, 'split', split)
    with pytest.raises(NetworkError, match='project settings changed'):
        net.resplit_banked(slug, apply=True, log=lambda *_: None)
    assert rows(net, slug) == before
    assert '-DRETAIN_USER_SETTING' in net.cfg(net.project_row(slug))['compiler']['flags']
