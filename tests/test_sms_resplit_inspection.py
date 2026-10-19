"""All preview records are inspectable without compiling or saving legacy stored metadata."""
import json
from pathlib import Path

import pytest

from decompnet.app import sms_resplit_source_check as checker
from decompnet.network import NetworkError

from .test_sms import make_rom
from .test_sms_profile_migration import project as fixture_project, proposal, snapshot

project = fixture_project
PRIVATE = 'authored saved source sentinel, excluded from inspection'


@pytest.fixture
def crowded(project, monkeypatch):
    net, original_slug = project
    platform = net.cfg(net.project_row(original_slug))['platform']
    offsets = [0x2000 + i * 8 for i in range(130)]
    code = {0: bytes.fromhex('c30010'), 0x1000: b''.join(b'\xcd' + off.to_bytes(2, 'little') for off in offsets) + b'\x18\xfe'}
    code.update({off: bytes((0x3E, i, 0xC9)) for i, off in enumerate(offsets)})
    code.update({off: b'\xc9' for off in (*range(8, 0x40, 8), 0x66)})
    image = make_rom(region=4 if platform == 'sms' else 6, code=code)
    slug = net.import_rom(image, name=f'authored-crowded.{platform}', confirmed=True, log=lambda *_: None)
    net.sms.configure(slug, 'sega', **{key: value for key, value in proposal().items() if key != 'mapper'})
    pid = net.project_row(slug)['id']
    found = net.store.all('SELECT rom_offset FROM functions WHERE project_id=?', pid)
    assert set(offsets) <= {row['rom_offset'] for row in found}
    with net.store.tx() as db:
        # Independently seed legacy stored work. Inspection must neither trust nor compile it.
        for i in range(130):
            name = f'OldEntry{i}' if i else '<img src=x>' * 100
            db.execute('INSERT INTO functions(project_id,name,rom_offset,vram,size,target,status,matched_source,meta) '
                       'VALUES(?,?,?,?,?,?,?,?,?)',
                       (pid, name, 0x3000 + i * 8, 0x3000 + i * 8, 1, b'\0', 'documented', PRIVATE, '{"review":"old"}'))
        large = db.execute('INSERT INTO functions(project_id,name,rom_offset,vram,size,target,status) '
                           'VALUES(?,?,?,?,?,?,?)', (pid, 'OldSpanningEntry', 0x1FFF, 0x1FFF, 1041,
                                                    image[0x1FFF:0x1FFF + 1041], 'asm')).lastrowid
    def never_check(*args, **kwargs):
        raise AssertionError('inspection must not compile or accept source')
    monkeypatch.setattr(checker, 'check', never_check)
    return net, slug, large


@pytest.mark.parametrize('migrate', [False, True])
def test_every_changed_check_and_overlap_record_can_be_inspected_without_saving(crowded, migrate):
    net, slug, large = crowded
    args = {'profile': proposal()} if migrate else {}
    before = snapshot(net, slug)
    preview = net.resplit_banked(slug, **args, log=lambda *_: None)
    assert preview['changed_work_count'] == 131 and len(preview['changed_work']) == 100
    assert preview['source_revalidation_pending'] == 130 and preview['inspection_available']
    assert preview['source_revalidation_limits'] == {'functions': 32, 'seconds': 30}
    assert preview['changed_work'][0]['name_truncated'] and len(preview['changed_work'][0]['name']) == 512
    for kind, total in [('changed', 131), ('checks', 130), ('overlaps', 130)]:
        rows, offset = [], 0
        while offset is not None:
            selection = {'kind': kind, 'offset': offset, **({'function': large} if kind == 'overlaps' else {})}
            result = net.resplit_banked(slug, **args, expected_plan=preview['plan'], inspection=selection, log=lambda *_: None)
            assert set(result) == {'plan', 'inspection'} and result['plan'] == preview['plan']
            page = result['inspection']
            assert page['total'] == total and page['offset'] == offset and 0 < len(page['rows']) <= 100
            assert PRIVATE not in json.dumps(result) and 'target' not in json.dumps(result)
            if kind == 'overlaps':
                assert page['function']['id'] == large
            rows.extend(page['rows'])
            offset = page['next_offset']
        key = 'rom_offset' if kind == 'overlaps' else 'id'
        assert len(rows) == len({row[key] for row in rows}) == total
        if kind == 'checks':
            assert all(row['proposed'] is None for row in rows)
        empty = net.resplit_banked(slug, **args, expected_plan=preview['plan'], inspection={**selection, 'offset': total}, log=lambda *_: None)
        assert empty['inspection']['rows'] == [] and empty['inspection']['next_offset'] is None
    assert snapshot(net, slug) == before and not net.resplit_history(slug)['history']


@pytest.mark.parametrize('selection', [False, [], {}, {'kind': 'unknown', 'offset': 0},
    {'kind': 'changed'}, {'kind': 'changed', 'offset': True}, {'kind': 'changed', 'offset': -1},
    {'kind': 'checks', 'offset': '0'}, {'kind': 'checks', 'offset': 2**63},
    {'kind': 'checks', 'offset': 0, 'limit': 1000}, {'kind': 'overlaps', 'offset': 0},
    {'kind': 'overlaps', 'offset': 0, 'function': True}, {'kind': 'overlaps', 'offset': 0, 'function': 0}])
def test_invalid_inspection_requests_fail_before_discovery(project, selection, monkeypatch):
    from decompnet.rom import sms

    net, slug = project
    before = snapshot(net, slug)
    def never_split(*args, **kwargs):
        raise AssertionError('invalid inspection must fail before discovery')
    monkeypatch.setattr(sms, 'split', never_split)
    with pytest.raises(NetworkError):
        net.resplit_banked(slug, expected_plan='a' * 64, inspection=selection, log=lambda *_: None)
    assert snapshot(net, slug) == before


@pytest.mark.parametrize('edit', ['note', 'sidecar', 'profile', 'source', 'rom'])
def test_inspection_cannot_mix_pages_after_work_input_or_profile_changes(project, edit):
    net, slug = project
    requested = proposal()
    preview = net.resplit_banked(slug, profile=requested, log=lambda *_: None)
    proj = net.project_row(slug)
    if edit in ('sidecar', 'rom'):
        path = Path(proj['root']) / net.cfg(proj)['rom']['file']
        if edit == 'sidecar':
            path.with_suffix('.sym').write_text('00:0200 AuthoredEdit\n')
        else:
            image = bytearray(path.read_bytes())
            image[0x200] ^= 1
            path.write_bytes(image)
    elif edit == 'profile':
        requested = proposal('codemasters')
    else:
        with net.store.tx() as db:
            if edit == 'note':
                db.execute('INSERT INTO notes(project_id,text) VALUES(?,?)', (proj['id'], 'New authored evidence'))
            else:
                db.execute('UPDATE functions SET best_source=? WHERE project_id=?', (PRIVATE, proj['id']))
    with pytest.raises(NetworkError, match='stale|differs'):
        net.resplit_banked(slug, profile=requested, expected_plan=preview['plan'],
                          inspection={'kind': 'changed', 'offset': 0}, log=lambda *_: None)
    assert not net.resplit_history(slug)['history']


def test_inspection_requires_its_own_preview_and_cannot_apply_or_select_foreign_rows(project):
    net, slug = project
    before = snapshot(net, slug)
    request = {'kind': 'changed', 'offset': 0}
    with pytest.raises(NetworkError, match='preview before'):
        net.resplit_banked(slug, inspection=request, log=lambda *_: None)
    preview = net.resplit_banked(slug, log=lambda *_: None)
    with pytest.raises(NetworkError, match='read-only'):
        net.resplit_banked(slug, apply=True, expected_plan=preview['plan'], inspection=request, log=lambda *_: None)
    for selection in ({'kind': 'changed', 'offset': 1}, {'kind': 'overlaps', 'offset': 0, 'function': 999999}):
        with pytest.raises(NetworkError, match='outside|unavailable'):
            net.resplit_banked(slug, expected_plan=preview['plan'], inspection=selection, log=lambda *_: None)
    assert snapshot(net, slug) == before and not net.resplit_history(slug)['history']


def test_inspection_cannot_be_requested_for_other_banked_lanes():
    from decompnet.app.banked_resplit_inspection import parse

    for arch in ('lr35902', 'mos6502'):
        with pytest.raises(NetworkError, match='only for SMS/GG'):
            parse({'kind': 'changed', 'offset': 0}, arch=arch, apply=False, expected_plan='a' * 64)


@pytest.mark.parametrize('change', [{'platform': 'nes'}, {'kind': 'source'}, {'link': {'host': 'authored'}}])
def test_z80_arch_alone_does_not_authorize_inspecting_another_project_kind(project, change):
    net, slug = project
    net._update_cfg(slug, lambda cfg: cfg.update(change))
    before = snapshot(net, slug)
    with pytest.raises(NetworkError, match='local SMS/GG ROM projects'):
        net.resplit_banked(slug, expected_plan='a' * 64, inspection={'kind': 'checks', 'offset': 0}, log=lambda *_: None)
    assert snapshot(net, slug) == before
