"""Retained source is checked by actual tools against the proposed SMS/GG bytes and coordinates."""
from dataclasses import replace
from pathlib import Path

import pytest

from decompnet.app import banked_resplit_history as history
from decompnet.app.sms_resplit_source_check import check
from decompnet.app.engine import RomNetwork
from decompnet.rom import gb_build, sms, sms_asm

from .test_sms import make_rom

ASM = ('; Returns without changing the caller registers or flags.\n'
       '; Input: caller state. Output: caller state is preserved.\nPreservedReturn:\n    ret\n')
C = 'unsigned char func_000_0200(void) { return 7; }\n'


@pytest.fixture(params=[('sms', 4), ('gg', 6)], ids=['sms', 'gg'])
def project(tmp_path, request):
    platform, region = request.param
    net = RomNetwork(tmp_path / 'state.db', tmp_path / 'projects')
    net.auto_install_tools = False
    net.on_match = lambda *_: None  # These checks isolate resplitting from asynchronous twin search.
    slug = net.import_rom(make_rom(region=region, code={0: bytes.fromhex('cd0002 18fe'), 0x200: bytes.fromhex('3e07c9')}),
                          name=f'fixture.{platform}', confirmed=True, log=lambda *_: None)
    net.sms.configure(slug, 'sega', 'annotated-original', 'The authored fixture declares its cartridge selector wiring.')
    return net, slug


def inputs(net, slug):
    proj = net.project_row(slug)
    before = history.capture(net, proj)
    cfg = net.cfg(proj)
    image = (Path(proj['root']) / cfg['rom']['file']).read_bytes()
    report = {}
    functions = sms.functions(image, report=report)
    names = {fn.rom: next((row['name'] for row in before['tables']['functions'] if row['rom_offset'] == fn.rom), fn.name)
             for fn in functions}
    candidate = next(fn for fn in functions if fn.rom == 0x200)
    row = next(row for row in before['tables']['functions'] if row['rom_offset'] == 0x200)
    return before, row, candidate, names, functions, report.get('regions', [])


@pytest.mark.skipif(not gb_build.available('z80'), reason='needs GBDK/SDCC')
def test_c_revalidation_is_a_byte_reference_under_the_current_unit_context(project):
    net, slug = project
    agent, _ = net.local_agent('fixture_writer')
    row = net.store.one('SELECT * FROM functions WHERE project_id=? AND rom_offset=512', net.project_row(slug)['id'])
    accepted = net.attempt(agent, row['name'], C, slug)
    assert accepted['matched'], accepted['text']
    values = inputs(net, slug)
    before, row, candidate, names, functions, regions = values
    result = check(*values)
    assert result.state == 'passed' and result.source == C
    assert result.report()['scope'] == 'function-byte-reference'
    changed = check(before, row, replace(candidate, code=bytes.fromhex('3e08c9')), names, functions, regions)
    assert changed.state == 'failed' and 'bytes differ' in changed.problems[0]
    assert history.capture(net, net.project_row(slug)) == before and not net.store.conn.in_transaction


@pytest.mark.skipif(not sms_asm.available(), reason='needs WLA-DX')
def test_assembly_revalidation_uses_proposed_cpu_and_source_geometry(project):
    net, slug = project
    proj = net.project_row(slug)
    # An older split declared the same physical return routine in slot 2; the proposed entry uses slot 0.
    path = Path(proj['root']) / net.cfg(proj)['rom']['file']
    # Keep the actual input frozen: use the real three-byte body and a documented instruction form.
    source = ASM.replace('    ret\n', '    ld a, 7\n    ret\n').replace('without changing the caller registers or flags',
        'with the authored value in A and unchanged flags').replace('caller state is preserved', 'A holds the authored value')
    row = net.store.one('SELECT * FROM functions WHERE project_id=? AND rom_offset=512', proj['id'])
    with net.store.tx() as db:
        db.execute("UPDATE functions SET vram=33280,status='asm' WHERE id=?", (row['id'],))
    agent, _ = net.local_agent('fixture_writer')
    accepted = net.document_function(agent, slug, row['name'], source)
    assert accepted.startswith('✅ DOCUMENTED:'), accepted
    values = inputs(net, slug)
    result = check(*values)
    assert result.state == 'passed' and result.report()['scope'] == 'assembly-byte-and-placement'
    before, row, candidate, names, functions, regions = values
    assert row['vram'] == 0x8200 and candidate.vram == 0x200
    failed = check(before, row, replace(candidate, code=b'\xc9'), names, functions, regions)
    assert failed.state == 'failed' and 'byte equality/build' in failed.problems
    assert path.read_bytes() == make_rom(region=4 if net.cfg(proj)['platform'] == 'sms' else 6,
                                       code={0: bytes.fromhex('cd0002 18fe'), 0x200: bytes.fromhex('3e07c9')})
    assert history.capture(net, net.project_row(slug)) == before


def test_missing_tools_or_context_never_promotes_retained_source(project, monkeypatch):
    net, slug = project
    values = list(inputs(net, slug))
    values[1] = {**values[1], 'status': 'documented', 'matched_source': ASM}
    monkeypatch.setattr(sms_asm, 'available', lambda: False)
    assert check(*values).state == 'unresolved'
    values[1] = {**values[1], 'status': 'matched', 'matched_source': C}
    monkeypatch.setattr(gb_build, 'available', lambda *_: False)
    assert check(*values).state == 'unresolved'
    assert C not in str(check(*values).report())


def test_invalid_coordinates_and_oversized_source_stop_before_tool_execution(project, monkeypatch):
    net, slug = project
    before, row, candidate, names, functions, regions = inputs(net, slug)
    row = {**row, 'status': 'documented', 'matched_source': ASM}
    calls = []
    monkeypatch.setattr(sms_asm, 'judge', lambda *_: calls.append(True))
    assert check(before, row, replace(candidate, vram=0x8210), names, functions, regions).state == 'unresolved'
    row['matched_source'] = 'x' * 65537
    assert check(before, row, candidate, names, functions, regions).state == 'unresolved'
    assert not calls


def test_removed_entry_and_external_headers_remain_unresolved(project, monkeypatch):
    import json

    net, slug = project
    values = list(inputs(net, slug))
    values[1] = {**values[1], 'status': 'matched', 'matched_source': C}
    values[0]['tables']['functions'].append({'name': 'RetiredEntry'})
    values[1]['matched_source'] = C.replace('return 7', 'return RetiredEntry()')
    monkeypatch.setattr(gb_build, 'compile_function', lambda *_a, **_kw: pytest.fail('unresolved inputs cannot compile'))
    assert 'without a proposed entry' in check(*values).problems[0]
    values[1]['matched_source'] = C
    cfg = json.loads(values[0]['project']['config'])
    cfg['compiler']['include_dirs'] = ['fixture-includes']
    values[0]['project']['config'] = json.dumps(cfg)
    monkeypatch.setattr(gb_build, 'available', lambda *_: True)
    assert 'dependency context' in check(*values).problems[0]


@pytest.mark.skipif(not sms_asm.available(), reason='needs WLA-DX')
def test_expired_assembly_budget_stops_before_running_a_tool(project, monkeypatch):
    net, slug = project
    values = list(inputs(net, slug))
    values[1] = {**values[1], 'status': 'documented', 'matched_source': ASM.replace('    ret\n', '    ld a, 7\n    ret\n')}
    monkeypatch.setattr(gb_build, '_run', lambda *_a, **_kw: pytest.fail('expired budget cannot launch a process'))
    result = check(*values, timeout=0)
    assert result.state == 'unresolved' and 'time budget' in result.problems[0]
