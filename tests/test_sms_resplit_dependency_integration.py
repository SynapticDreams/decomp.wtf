"""Actual GBDK validation uses frozen configured files; live edits invalidate resplit/undo."""
import base64
import copy
import hashlib
import json
from pathlib import Path

import pytest

from decompnet.app import banked_resplit_archive as archive, banked_resplit_history as history, banked_resplit_state as state
from decompnet.app import sms_resplit_source_check as checker
from decompnet.network import NetworkError
from decompnet.rom import gb_build

from .test_sms_resplit_source_check import project as fixture_project, inputs

project = fixture_project
SOURCE = '#include "nested/value.h"\nunsigned char func_000_0200(void) { return VALUE; }\n'


def row(net, slug):
    return net.store.one('SELECT * FROM functions WHERE project_id=? AND rom_offset=512', net.project_row(slug)['id'])


def capture(net, slug):
    return history.capture(net, net.project_row(slug))


@pytest.fixture
def included(project):
    net, slug = project
    proj = net.project_row(slug)
    root = Path(proj['root'])
    for name, value in (('default', 99), ('first', 3), ('second', 7)):
        folder = root / name / 'nested'
        folder.mkdir(parents=True)
        (folder / 'value.h').write_bytes(f'#define VALUE {value}\r\n'.encode())
    (root / 'second/payload.bin').write_bytes(b'\0\x80\xff')
    cfg = net.cfg(proj)
    cfg['compiler']['include_dirs'] = ['default']
    cfg['compiler']['units'] = {'bank000': {'include_dirs': ['first', 'second']}}
    with net.store.tx() as db:
        db.execute('UPDATE projects SET config=? WHERE id=?', (json.dumps(cfg), proj['id']))
    return net, slug, root / 'second/nested/value.h'


@pytest.mark.skipif(not gb_build.available('z80'), reason='needs GBDK/SDCC')
@pytest.mark.parametrize('changed', [False, True])
def test_nested_unit_dependencies_are_revalidated_and_recoverable_without_layout_changes(included, changed, monkeypatch):
    net, slug, header = included
    agent, _ = net.local_agent('fixture_writer')
    fn = row(net, slug)
    assert net.attempt(agent, fn['name'], SOURCE, slug)['matched']
    if changed:
        header.write_text('#define VALUE 8\n')
    before = capture(net, slug)
    calls, original = [], gb_build.compile_function
    def compile_(*args, **kwargs):
        assert not net.store.conn.in_transaction
        paths = kwargs['include_dirs']
        assert len(paths) == 2 and str(header.parent.parent) not in paths
        assert (Path(paths[-1]) / 'nested/value.h').read_bytes() == header.read_bytes()
        calls.append(paths)
        return original(*args, **kwargs)
    monkeypatch.setattr(gb_build, 'compile_function', compile_)
    preview = net.resplit_banked(slug, log=lambda *_: None)
    assert preview['source_revalidation_pending'] == 1 and not calls
    result = net.resplit_banked(slug, apply=True, expected_plan=preview['plan'], log=lambda *_: None)
    current = row(net, slug)
    assert current['id'] == fn['id'] and current['status'] == ('open' if changed else 'matched')
    assert current['best_source'] == SOURCE and current['matched_source'] == (None if changed else SOURCE)
    assert result['source_revalidation']['failed' if changed else 'passed'] == 1
    meta = json.loads(current['meta'])['resplit_validation']
    assert meta['checked_source_sha256'] == hashlib.sha256(SOURCE.encode()).hexdigest()
    assert meta['checked_target_sha256'] == hashlib.sha256(current['target']).hexdigest()
    assert calls and not any(Path(path).exists() for paths in calls for path in paths)
    listing = archive.read(net, slug, result['history_id'], function_id=fn['id'])
    manifest = json.loads(archive.read(net, slug, result['history_id'], function_id=fn['id'], item='dependencies')['text'])
    assert manifest['state'] == 'captured' and manifest['configured'] == ['first', 'second']
    records = [item for item in listing['items'] if item['key'].startswith('dependency:')]
    latest = next(item for item in records if item['provenance']['directory'] == manifest['order'][-1] and
                  item['provenance']['path'] == 'nested/value.h')
    raw = archive.read(net, slug, result['history_id'], function_id=fn['id'], item=latest['key'])
    assert raw['text'].encode() == header.read_bytes() and raw['sha256'] == latest['provenance']['content_sha256']
    binary = next(item for item in records if item['provenance']['path'] == 'payload.bin')
    encoded = archive.read(net, slug, result['history_id'], function_id=fn['id'], item=binary['key'])
    assert binary['provenance']['encoding'] == 'base64' and base64.b64decode(encoded['text']) == b'\0\x80\xff'
    if changed:
        current_state = capture(net, slug)
        with pytest.raises(NetworkError, match='does not revalidate'):
            net.undo_resplit(slug, result['history_id'])
        assert capture(net, slug) == current_state
    else:
        net.undo_resplit(slug, result['history_id'])
        assert capture(net, slug) == before


@pytest.mark.skipif(not gb_build.available('z80'), reason='needs GBDK/SDCC')
def test_direct_source_check_reads_frozen_bytes_after_live_header_changes(included):
    net, slug, header = included
    agent, _ = net.local_agent('fixture_writer')
    fn = row(net, slug)
    assert net.attempt(agent, fn['name'], SOURCE, slug)['matched']
    values = list(inputs(net, slug))
    header.write_text('#define VALUE 8\n')
    assert checker.check(*values).state == 'passed'  # The captured recipe still contains VALUE 7.
    current = list(inputs(net, slug))
    assert checker.check(*current).state == 'failed'


@pytest.mark.skipif(not gb_build.available('z80'), reason='needs GBDK/SDCC')
@pytest.mark.parametrize('when', ['preview', 'compile', 'transaction', 'undo'])
def test_external_edits_invalidate_stale_plans_apply_or_undo_without_losing_current_work(included, when, monkeypatch):
    net, slug, header = included
    fn = row(net, slug)
    agent, _ = net.local_agent('fixture_writer')
    assert net.attempt(agent, fn['name'], SOURCE, slug)['matched']
    preview = net.resplit_banked(slug, log=lambda *_: None)
    before = capture(net, slug)
    if when == 'preview':
        header.write_text('#define VALUE 8\n')
    elif when == 'compile':
        original = gb_build.compile_function
        def compile_(*args, **kwargs):
            header.write_text('#define VALUE 8\n')
            return original(*args, **kwargs)
        monkeypatch.setattr(gb_build, 'compile_function', compile_)
    elif when == 'transaction':
        original = history.mark_sms
        def mark(db, pid):
            original(db, pid)
            header.write_text('#define VALUE 8\n')
        monkeypatch.setattr(history, 'mark_sms', mark)
    else:
        result = net.resplit_banked(slug, apply=True, log=lambda *_: None)
        before = capture(net, slug)
        header.unlink()
    with pytest.raises(NetworkError, match='stale|changed|unavailable'):
        if when == 'undo':
            net.undo_resplit(slug, result['history_id'])
        else:
            net.resplit_banked(slug, apply=True, expected_plan=preview['plan'], log=lambda *_: None)
    assert capture(net, slug)['tables'] == before['tables']
    assert capture(net, slug)['project'] == before['project']
    if when != 'undo':
        assert not net.resplit_history(slug)['history']


def test_legacy_configured_include_snapshots_expose_missing_context_without_guessing(included):
    net, slug, _header = included
    before = capture(net, slug)
    before['inputs'].pop('compiler_dependencies')
    current = copy.deepcopy(before)
    with net.store.tx() as db:
        hid = history.record(db, net.project_row(slug)['id'], before, current, {})
    fid = row(net, slug)['id']
    manifest = json.loads(archive.read(net, slug, hid, function_id=fid, item='dependencies')['text'])
    assert manifest['state'] == 'unavailable' and 'dependency context' in manifest['reason']
    with pytest.raises(NetworkError, match='no compiler dependency context'):
        net.undo_resplit(slug, hid)
    assert state.decode(net.store.one('SELECT before_state FROM resplit_history WHERE id=?', hid)['before_state'],
                        state.encode(before)[1]) == before


@pytest.mark.skipif(not gb_build.available('z80'), reason='needs GBDK/SDCC')
def test_overlay_directory_file_conflict_cannot_retain_an_old_c_match(included):
    net, slug, header = included
    fn = row(net, slug)
    agent, _ = net.local_agent('fixture_writer')
    assert net.attempt(agent, fn['name'], SOURCE, slug)['matched']
    root = header.parents[2]
    (root / 'first/blocked').write_bytes(b'authored file')
    (root / 'second/blocked').mkdir()
    result = net.resplit_banked(slug, apply=True, log=lambda *_: None)
    current = row(net, slug)
    assert current['matched_source'] is None and current['best_source'] == SOURCE
    assert result['source_revalidation']['unresolved'] == 1


@pytest.mark.skipif(not gb_build.available('z80'), reason='needs GBDK/SDCC')
@pytest.mark.parametrize('unit', ['render', ''], ids=['named-unit', 'default-unit'])
def test_changed_coordinates_preserve_the_compiler_unit_that_was_validated(included, unit):
    net, slug, _header = included
    fn, proj = row(net, slug), net.project_row(slug)
    cfg = net.cfg(proj)
    cfg['compiler']['include_dirs'] = ['second']
    cfg['compiler']['units'] = {'bank000': {'include_dirs': ['first']},
                               'render': {'include_dirs': ['second']}, '': {'include_dirs': ['second']}}
    with net.store.tx() as db:
        db.execute('UPDATE projects SET config=? WHERE id=?', (json.dumps(cfg), proj['id']))
        db.execute('UPDATE functions SET unit=? WHERE id=?', (unit, fn['id']))
    agent, _ = net.local_agent('fixture_writer')
    assert net.attempt(agent, fn['name'], SOURCE, slug)['matched']
    with net.store.tx() as db:
        db.execute('UPDATE functions SET vram=33280 WHERE id=?', (fn['id'],))
    result = net.resplit_banked(slug, apply=True, log=lambda *_: None)
    current = row(net, slug)
    assert current['id'] != fn['id'] and current['vram'] == 512 and current['unit'] == unit
    assert current['matched_source'] == SOURCE and result['source_revalidation']['passed'] == 1
    assert net.attempt(agent, current['name'], SOURCE, slug)['score'] == 0
