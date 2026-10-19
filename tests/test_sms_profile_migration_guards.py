"""Migration refuses unsafe inputs and remains recoverable through consecutive model changes."""
from pathlib import Path
from types import SimpleNamespace

import pytest

from decompnet.network import NetworkError

from .test_sms_profile_migration import project as fixture_project, proposal, snapshot

project = fixture_project


@pytest.mark.parametrize('change', ['rom', 'platform', 'kind', 'link'])
def test_profile_proposal_refuses_changed_input_or_nonlocal_sms_context(project, change):
    net, slug = project
    if change == 'rom':
        proj = net.project_row(slug)
        path = Path(proj['root']) / net.cfg(proj)['rom']['file']
        image = bytearray(path.read_bytes())
        image[0x200] ^= 1
        path.write_bytes(image)
    else:
        value = {'platform': 'nes', 'kind': 'source', 'link': {'host': 'authored'}}[change]
        net._update_cfg(slug, lambda cfg: cfg.update({change: value}))
    # A broken input is deliberately captured without trying to validate it again.
    cfg = net.cfg(net.project_row(slug))
    rows = net.store.all('SELECT * FROM functions WHERE project_id=?', net.project_row(slug)['id'])
    with pytest.raises(NetworkError):
        net.resplit_banked(slug, profile=proposal(), log=lambda *_: None)
    assert net.cfg(net.project_row(slug)) == cfg
    assert net.store.all('SELECT * FROM functions WHERE project_id=?', net.project_row(slug)['id']) == rows
    assert not net.resplit_history(slug)['history']


@pytest.mark.parametrize('job', ['autopilot', 'twins', 'permuter'])
def test_running_analysis_blocks_profile_apply(project, job, monkeypatch):
    net, slug = project
    preview = net.resplit_banked(slug, profile=proposal(), log=lambda *_: None)
    before = snapshot(net, slug)
    if job == 'autopilot':
        net.autopilots[slug] = {'state': 'running'}
    elif job == 'twins':
        net.twins.jobs[slug] = SimpleNamespace(state='running')
    else:
        monkeypatch.setattr(net.permuter, 'status', lambda *_: {'state': 'running'})
    with pytest.raises(NetworkError, match='background analysis'):
        net.resplit_banked(slug, profile=proposal(), apply=True, expected_plan=preview['plan'], log=lambda *_: None)
    assert snapshot(net, slug) == before and not net.resplit_history(slug)['history']


def test_consecutive_profile_transitions_undo_in_order_with_their_original_work(project):
    net, slug = project
    original = snapshot(net, slug)
    def migrate(mapper):
        requested = proposal(mapper)
        preview = net.resplit_banked(slug, profile=requested, log=lambda *_: None)
        return net.resplit_banked(slug, profile=requested, apply=True, expected_plan=preview['plan'], log=lambda *_: None)
    first = migrate('mapperless')
    intermediate = snapshot(net, slug)
    second = migrate('codemasters')
    with pytest.raises(NetworkError, match='latest'):
        net.undo_resplit(slug, first['history_id'])
    net.undo_resplit(slug, second['history_id'])
    assert snapshot(net, slug) == intermediate
    net.undo_resplit(slug, first['history_id'])
    assert snapshot(net, slug) == original


@pytest.mark.parametrize('size,mapper', [(0x10000, 'mapperless'), (0xC000, 'codemasters')])
def test_proposed_model_rejects_incompatible_input_size_without_saving(project, size, mapper):
    from .test_sms import make_rom

    net, original_slug = project
    platform = net.cfg(net.project_row(original_slug))['platform']
    slug = net.import_rom(make_rom(size=size, region=4 if platform == 'sms' else 6, code={0: b'\xc9'}),
                          name=f'authored-size.{platform}', confirmed=True, log=lambda *_: None)
    before = snapshot(net, slug)
    with pytest.raises(NetworkError):
        net.resplit_banked(slug, profile=proposal(mapper), log=lambda *_: None)
    assert snapshot(net, slug) == before and not net.resplit_history(slug)['history']
