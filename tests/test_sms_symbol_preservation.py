"""Importing declarations cannot rename or discard actual accepted assembly/C work."""
from pathlib import Path

import pytest

from decompnet.rom import gb_build, sms_asm
from .sms_wla_fixture import bank_zero_layout
from .test_export_sms import exported as fixture_exported
from .test_sms_profile_migration import project as fixture_compiled_project, function
from .test_sms_resplit_source_check import C

exported = fixture_exported
compiled_project = fixture_compiled_project
pytestmark = pytest.mark.skipif(not sms_asm.available(), reason='needs pinned WLA-DX')


def test_declared_symbol_import_retains_actual_documented_source_and_resplit_undo(exported):
    net, slug, _result, _out = exported
    proj = net.project_row(slug)
    cfg = net.cfg(proj)
    image = (Path(proj['root']) / cfg['rom']['file']).read_bytes()
    layout = bank_zero_layout(image)
    layout['views'][0].update(offset=0x200, size=0x10)
    before = dict(net._function('ShowMenu', slug))
    net.import_symbols(slug, '[labels]\n00:0200 ImportedName\n00:0200 OtherAlias\n', 'names.sym', layout=layout)
    assert dict(net._function('ShowMenu', slug)) == before
    assert not net.overview(slug)['export']['current']  # Source provenance changed; a previous check stays historical.
    result = net.resplit_banked(slug, apply=True, log=lambda *_: None)
    after = net._function('ShowMenu', slug)
    assert after['status'] == 'documented' and after['matched_source'] == before['matched_source']
    assert not net.store.one('SELECT 1 FROM functions WHERE project_id=? AND name=?', proj['id'], 'ImportedName')
    net.undo_resplit(slug, result['history_id'])
    restored = net._function('ShowMenu', slug)
    assert restored['status'] == 'documented' and restored['matched_source'] == before['matched_source']


@pytest.mark.skipif(not gb_build.available('z80'), reason='needs pinned GBDK')
def test_declared_symbol_import_retains_actual_c_match_and_resplit_undo(compiled_project):
    net, slug = compiled_project
    fn = function(net, slug)
    agent, _ = net.local_agent('authored_symbol_writer')
    assert net.attempt(agent, fn['name'], C, slug)['matched']
    proj = net.project_row(slug)
    image = (Path(proj['root']) / net.cfg(proj)['rom']['file']).read_bytes()
    layout = bank_zero_layout(image)
    layout['views'][0].update(offset=0x200, size=3)
    before = dict(function(net, slug))
    net.import_symbols(slug, '[labels]\n00:0200 ImportedAlternative\n', 'names.sym', layout=layout)
    assert dict(function(net, slug)) == before
    result = net.resplit_banked(slug, apply=True, log=lambda *_: None)
    after = function(net, slug)
    assert after['name'] == before['name'] and after['matched_source'] == C and after['status'] == 'matched'
    net.undo_resplit(slug, result['history_id'])
    restored = function(net, slug)
    assert restored['name'] == before['name'] and restored['matched_source'] == C and restored['status'] == 'matched'
