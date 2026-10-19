"""Pinned tools prove qualified corrections change discovery while retaining accepted C/assembly work."""
from pathlib import Path

import pytest

from decompnet.app import banked_resplit_history as history
from decompnet.app.engine import RomNetwork
from decompnet.network import NetworkError
from decompnet.rom import gb_build, sms_asm
from .test_sms import make_rom
from .test_sms_corrections import CODE
from .test_sms_resplit_source_check import ASM, C
from .test_sms_profile_migration import function
from .test_sms_correction_facts import WHY, draft, save, review

pytestmark = pytest.mark.skipif(not gb_build.available('z80') or not sms_asm.available(), reason='needs pinned GBDK and WLA-DX')


@pytest.fixture(params=['sms', 'gg'])
def project(tmp_path, request):
    platform = request.param
    net = RomNetwork(tmp_path / 'facts.db', tmp_path / 'projects')
    net.auto_install_tools = False
    net.on_match = lambda *_: None
    slug = net.import_rom(make_rom(size=0x20000, region=4 if platform == 'sms' else 6,
                          code={**CODE, 0: bytes.fromhex('cd0002 c30001'), 0x200: bytes.fromhex('3e07c9')}),
                          name=f'fixture.{platform}', confirmed=True, log=lambda *_: None)
    net.sms.configure(slug, 'sega', 'annotated-original', 'The authored fixture declares its cartridge selector wiring.')
    return net, slug


def accepted(net, slug, agent, kind):
    fn = function(net, slug)
    if kind == 'c':
        assert net.attempt(agent, fn['name'], C, slug)['matched']
        return C
    source = ASM.replace('    ret\n', '    ld a, 7\n    ret\n').replace('without changing the caller registers or flags',
        'with the authored result in A and unchanged flags').replace('caller state is preserved', 'A holds seven')
    net.store.conn.execute("UPDATE functions SET status='asm' WHERE id=?", (fn['id'],))
    assert net.document_function(agent, slug, fn['name'], source).startswith('✅ DOCUMENTED:')
    return source


@pytest.mark.parametrize('kind', ['c', 'asm'])
def test_qualified_five_kinds_drive_discovery_and_preserve_real_source_through_resplit_undo(project, kind):
    net, slug = project
    agent, _ = net.local_agent('integration_writer')
    source = accepted(net, slug, agent, kind)
    records = []
    for hint, at, count in [('operands', '00:0300', 1), ('noreturn', '00:0400', 0),
                            ('table', '00:0500', 2), ('code', '00:0700', 0), ('data', '00:0800', 3)]:
        item = save(net, slug, agent, {'kind': hint, 'at': at, 'count': count, 'reason': WHY})['correction']
        records.append(item['id'])
    assert not net._hints(net.project_row(slug))['entries']
    pending = net.resplit_banked(slug, log=lambda *_: None)
    assert pending['corrections'] == 0
    for cid in records:
        assert review(net, slug, cid)['correction']['active']
    before = history.capture(net, net.project_row(slug))
    applied = net.resplit_banked(slug, apply=True, log=lambda *_: None)
    assert applied['corrections'] == 5
    starts = {row['rom_offset'] for row in net.store.all('SELECT rom_offset FROM functions WHERE project_id=?', net.project_row(slug)['id'])}
    assert {0x600, 0x620, 0x700, 0x14000} <= starts
    assert not {0x800, 0x250, 0x18000} & starts
    assert function(net, slug)['matched_source'] == source
    net.undo_resplit(slug, applied['history_id'])
    assert history.capture(net, net.project_row(slug)) == before
    assert function(net, slug)['matched_source'] == source
    assert all(net.inspect_correction(slug, cid)['active'] for cid in records)


@pytest.mark.parametrize('kind', ['c', 'asm'])
def test_pending_and_forged_data_cannot_override_actual_accepted_source_and_review_refuses_it(project, kind):
    net, slug = project
    agent, _ = net.local_agent('protected_writer')
    source = accepted(net, slug, agent, kind)
    request = draft('data')
    request['annotation']['target'].update(offset=0x200, size=3)
    request['at'] = '00:0200'
    item = save(net, slug, agent, request)['correction']
    assert item['conflict'] and not item['active']
    with pytest.raises(NetworkError, match='bytes are code'):
        net.review_correction(slug, item['id'], True)
    with pytest.raises(NetworkError, match='bytes are code'):
        net.correct_split(agent, slug, 'data', '00:0200', WHY, 3)
    net.resplit_banked(slug, apply=True, log=lambda *_: None)
    assert function(net, slug)['matched_source'] == source
    assert not net._hints(net.project_row(slug))['data']
    assert review(net, slug, item['id'], False)['correction']['application'] == 'rejected'


@pytest.mark.parametrize('count', [True, 1.5, '2', None, -1])
def test_legacy_counts_are_strict_and_full_table_extents_stay_inside_the_rom(project, count):
    net, slug = project
    agent, _ = net.local_agent('bounds_writer')
    with pytest.raises(NetworkError, match='count must be an integer'):
        net.correct_split(agent, slug, 'data', '00:0100', WHY, count)
    for kind, size in [('data', 2), ('table', 2)]:
        with pytest.raises(NetworkError, match='past the end'):
            net.correct_split(agent, slug, kind, '07:3fff', WHY, size)
    assert not net.store.all('SELECT * FROM corrections')


def test_changed_original_input_disables_previously_reviewed_hints_without_erasing_evidence(project):
    net, slug = project
    agent, _ = net.local_agent('input_writer')
    item = save(net, slug, agent, {'kind': 'code', 'at': '00:0700', 'reason': WHY})['correction']
    review(net, slug, item['id'])
    raw = net.store.one('SELECT evidence FROM corrections')['evidence']
    proj = net.project_row(slug)
    path = Path(proj['root']) / net.cfg(proj)['rom']['file']
    original = path.read_bytes()
    changed = bytearray(original); changed[0x700] ^= 1; path.write_bytes(changed)
    assert net.inspect_correction(slug, item['id'])['application'] == 'unavailable'
    assert not net._hints(net.project_row(slug))['entries']
    assert net.store.one('SELECT evidence FROM corrections')['evidence'] == raw
    path.write_bytes(original)
    assert net.inspect_correction(slug, item['id'])['active']
