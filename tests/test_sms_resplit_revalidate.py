"""Actual SMS/GG resplits rejudge accepted source without inheriting old target scores."""
import json
from pathlib import Path

import pytest

from decompnet.app import sms_resplit_revalidate as revalidate, sms_resplit_source_check as checker
from decompnet.app import banked_resplit_history as history
from decompnet.network import NetworkError
from decompnet.rom import gb_build, sms_asm

from .test_sms_resplit_source_check import project as fixture_project, C, ASM

project = fixture_project


def row(net, slug):
    return net.store.one('SELECT * FROM functions WHERE project_id=? AND rom_offset=512', net.project_row(slug)['id'])


def capture(net, slug):
    return history.capture(net, net.project_row(slug))


@pytest.mark.skipif(not gb_build.available('z80'), reason='needs GBDK/SDCC')
@pytest.mark.parametrize('context_changed', [False, True])
def test_c_resplit_rechecks_bytes_and_unit_header_and_preserves_provenance(project, context_changed, monkeypatch):
    net, slug = project
    fn = row(net, slug)
    agent, _ = net.local_agent('fixture_writer')
    source = C.replace('return 7', 'return AUTHORED_VALUE')
    with net.store.tx() as db:
        db.execute('UPDATE context_versions SET header=? WHERE project_id=?',
                   ('#define AUTHORED_VALUE 99\n', fn['project_id']))
        db.execute('INSERT INTO context_versions(project_id,version,unit,header) VALUES(?,2,?,?)',
                   (fn['project_id'], fn['unit'], '#define AUTHORED_VALUE 7\n'))
    assert net.attempt(agent, fn['name'], source, slug)['matched']
    with net.store.tx() as db:
        db.execute('UPDATE functions SET vram=33280,meta=? WHERE id=?',
                   (json.dumps({'review': 'retain fixture evidence', 'edges': {'1': 1234}}), fn['id']))
        db.execute('INSERT INTO notes(project_id,function_id,text) VALUES(?,?,?)',
                   (fn['project_id'], fn['id'], 'retain authored evidence'))
        if context_changed:
            db.execute('UPDATE context_versions SET header=? WHERE project_id=? AND unit=?',
                       ('#define AUTHORED_VALUE 8\n', fn['project_id'], fn['unit']))
    before = capture(net, slug)
    calls, original = [], gb_build.compile_function

    def compile_(*args, **kwargs):
        assert not net.store.conn.in_transaction
        calls.append(kwargs['context_header'])
        return original(*args, **kwargs)

    monkeypatch.setattr(gb_build, 'compile_function', compile_)
    preview = net.resplit_banked(slug, log=lambda *_: None)
    assert calls == [] and preview['source_revalidation_pending'] == 1
    result = net.resplit_banked(slug, apply=True, expected_plan=preview['plan'], log=lambda *_: None)
    current = row(net, slug)
    assert current['id'] != fn['id'] and current['vram'] == 512 and calls == [f'#define AUTHORED_VALUE {8 if context_changed else 7}\n']
    assert current['best_source'] == source
    assert current['matched_source'] == (None if context_changed else source)
    assert current['best_score'] == (None if context_changed else 0)
    assert current['status'] == ('open' if context_changed else 'matched')
    meta = json.loads(current['meta'])
    assert meta['review'] == 'retain fixture evidence' and 'edges' not in meta
    check = meta['resplit_validation']
    assert check['state'] == ('failed' if context_changed else 'passed')
    assert check['scope'] == 'function-byte-reference' and check['semantic_review'] == 'pending'
    assert check['origin']['function_id'] == fn['id']
    assert not net.store.one('SELECT 1 FROM attempts WHERE function_id=?', current['id'])
    assert net.store.one('SELECT function_id FROM notes WHERE text=?', 'retain authored evidence')['function_id'] == current['id']
    assert result['source_revalidation'][check['state']] == 1
    net.undo_resplit(slug, result['history_id'])
    assert capture(net, slug) == before


@pytest.mark.skipif(not sms_asm.available(), reason='needs WLA-DX')
def test_assembly_resplit_rechecks_new_cpu_then_inserts_retained_source_in_exact_export(project):
    net, slug = project
    fn = row(net, slug)
    source = ASM.replace('    ret\n', '    ld a, 7\n    ret\n')
    with net.store.tx() as db:
        db.execute("UPDATE functions SET vram=33280,status='asm' WHERE id=?", (fn['id'],))
    agent, _ = net.local_agent('fixture_writer')
    assert net.document_function(agent, slug, fn['name'], source).startswith('✅ DOCUMENTED:')
    old = row(net, slug)
    result = net.resplit_banked(slug, apply=True, log=lambda *_: None)
    current = row(net, slug)
    assert current['status'] == 'documented' and current['vram'] == 512 and current['name'] == old['name']
    assert result['source_revalidation']['passed'] == 1
    assert json.loads(current['meta'])['sample']
    exported = net.export_rom(slug, log=lambda *_: None)
    assert exported['identical'] and exported['documented'] == 1 and not exported['left_out']
    generated = (Path(exported['path']) / 'build/disassembly/bank_000.asm').read_text()
    assert '; documented in assembly: documented/PreservedReturn.asm' in generated
    assert current['matched_source'].strip() in generated
    proj = net.project_row(slug)
    cfg = net.cfg(proj)
    assert (Path(exported['path']) / 'build' / f"game.{cfg['platform']}").read_bytes() == (Path(proj['root']) / cfg['rom']['file']).read_bytes()


@pytest.mark.skipif(not gb_build.available('z80'), reason='needs GBDK/SDCC')
def test_budget_exhaustion_keeps_source_unaccepted_instead_of_old_match(project, monkeypatch):
    net, slug = project
    agent, _ = net.local_agent('fixture_writer')
    fn = row(net, slug)
    assert net.attempt(agent, fn['name'], C, slug)['matched']
    with net.store.tx() as db:
        db.execute('UPDATE functions SET vram=33280 WHERE id=?', (fn['id'],))
    monkeypatch.setattr(revalidate, 'MAX_CHECKS', 0)
    monkeypatch.setattr(checker, 'check', lambda *_a, **_kw: pytest.fail('budget must stop before the compiler'))
    result = net.resplit_banked(slug, apply=True, log=lambda *_: None)
    current = row(net, slug)
    assert current['matched_source'] is None and current['best_score'] is None and current['best_source'] == C
    assert result['source_revalidation'] == {'passed': 0, 'failed': 0, 'unresolved': 1}
    assert 'budget exhausted' in result['source_checks'][0]['problems'][0]


@pytest.mark.skipif(not gb_build.available('z80'), reason='needs GBDK/SDCC')
def test_concurrent_work_during_source_check_refuses_apply(project, monkeypatch):
    net, slug = project
    agent, _ = net.local_agent('fixture_writer')
    fn = row(net, slug)
    assert net.attempt(agent, fn['name'], C, slug)['matched']
    with net.store.tx() as db:
        db.execute('UPDATE functions SET vram=33280 WHERE id=?', (fn['id'],))
    before = capture(net, slug)
    original = checker.check

    def check(*args, **kwargs):
        result = original(*args, **kwargs)
        with net.store.tx() as db:
            db.execute('INSERT INTO notes(project_id,text) VALUES(?,?)', (fn['project_id'], 'concurrent source review'))
        return result

    monkeypatch.setattr(checker, 'check', check)
    with pytest.raises(NetworkError, match='changed during resplit'):
        net.resplit_banked(slug, apply=True, log=lambda *_: None)
    assert capture(net, slug)['tables']['functions'] == before['tables']['functions']
    assert net.store.one('SELECT 1 FROM notes WHERE text=?', 'concurrent source review')
    assert not net.resplit_history(slug)['history']


@pytest.mark.skipif(not gb_build.available('z80'), reason='needs GBDK/SDCC')
@pytest.mark.parametrize('claimed', [False, True])
def test_changed_layout_revalidates_retained_row_and_respects_its_claim(project, claimed):
    import time

    net, slug = project
    agent, _ = net.local_agent('fixture_writer')
    fn = row(net, slug)
    assert net.attempt(agent, fn['name'], C, slug)['matched']
    with net.store.tx() as db:
        db.execute('UPDATE functions SET vram=32768 WHERE project_id=? AND rom_offset=0', (fn['project_id'],))
        if claimed:
            db.execute('INSERT INTO claims VALUES(?,?,?,?)', (fn['id'], agent.id, time.time(), time.time() + 300))
    before = capture(net, slug)
    if claimed:
        with pytest.raises(NetworkError, match='release claims'):
            net.resplit_banked(slug, apply=True, log=lambda *_: None)
        assert capture(net, slug) == before
    else:
        result = net.resplit_banked(slug, apply=True, log=lambda *_: None)
        current = row(net, slug)
        assert current['id'] == fn['id'] and current['status'] == 'matched' and result['matched_kept'] == 1
        assert json.loads(current['meta'])['resplit_validation']['state'] == 'passed'
        assert capture(net, slug)['tables']['attempts'] == before['tables']['attempts']
