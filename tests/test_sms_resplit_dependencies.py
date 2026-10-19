"""Configured include contexts retain bytes, ordering and directories under explicit resource limits."""
import copy
from pathlib import Path

import pytest

from decompnet.app import sms_resplit_dependencies as deps, sms_resplit_dependency_context as context
from decompnet.network import NetworkError
from decompnet.project import compiler_settings


def config(*paths, units=None):
    return {'compiler': {'toolchain': 'gbdk-2020', 'include_dirs': list(paths), 'flags': ['--fsigned-char'],
                         'units': units or {}}}


def snapshot(root, cfg):
    bundle = deps.capture(root, cfg)
    return {'inputs': {'compiler_dependencies': bundle} if bundle else {}}


def test_no_includes_keeps_the_old_snapshot_input_shape(tmp_path):
    assert deps.capture(tmp_path, config()) is None
    with context.materialize({'inputs': {}}, compiler_settings(config(), 'bank000'), 'bank000') as paths:
        assert paths == ()
    with pytest.raises(deps.DependencyError, match='dependency context'):
        with context.materialize({'inputs': {}}, compiler_settings(config('inc'), 'bank000'), 'bank000'):
            pytest.fail('legacy configured inputs cannot be reconstructed from current files')


def test_ordered_unit_overrides_and_nested_files_are_frozen_and_cleaned(tmp_path):
    for name, value in (('first', b'#define VALUE 3\r\n'), ('second', b'#define VALUE 7\r\n')):
        directory = tmp_path / name / 'nested'
        directory.mkdir(parents=True)
        (directory / 'value.h').write_bytes(value)
        (directory / 'empty').mkdir()
    cfg = config('first', 'second', 'first', units={'bank000': {'include_dirs': ['second', 'first']}})
    before = snapshot(tmp_path, cfg)
    assert len(before['inputs']['compiler_dependencies']['directories']) == 2
    (tmp_path / 'first/nested/value.h').write_bytes(b'changed after capture')
    for unit, expected in (('bank000', [7, 3]), ('bank001', [3, 7, 3])):
        with context.materialize(before, compiler_settings(cfg, unit), unit) as paths:
            assert [int((Path(path) / 'nested/value.h').read_text().split()[-1]) for path in paths] == expected
            assert all((Path(path) / 'nested/empty').is_dir() for path in paths)
        assert not any(Path(path).exists() for path in paths)
    assert before != snapshot(tmp_path, cfg)


def test_an_empty_unit_override_and_missing_directory_keep_their_meanings(tmp_path):
    cfg = config('missing', units={'bank000': {'include_dirs': []}, '': {'include_dirs': ['other']}})
    before = snapshot(tmp_path, cfg)
    with context.materialize(before, compiler_settings(cfg, 'bank000'), 'bank000') as paths:
        assert paths == ()
    with context.materialize(before, compiler_settings(cfg, 'bank001'), 'bank001') as paths:
        assert len(paths) == 1 and not Path(paths[0]).exists()
    (tmp_path / 'missing').mkdir()
    assert snapshot(tmp_path, cfg) != before


def test_links_preserve_alias_paths_and_cycles_are_rejected(tmp_path):
    real = tmp_path / 'real'
    real.mkdir()
    (real / 'value.h').write_text('#define VALUE 7\n')
    try:
        (real / 'alias.h').symlink_to(real / 'value.h')
        (tmp_path / 'include').symlink_to(real, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip('host does not permit fixture symlinks')
    (tmp_path / 'missing-link').symlink_to(tmp_path / 'absent', target_is_directory=True)
    missing = snapshot(tmp_path, config('missing-link'))
    assert not missing['inputs']['compiler_dependencies']['directories'][0]['exists']
    cfg = config('include')
    before = snapshot(tmp_path, cfg)
    with context.materialize(before, compiler_settings(cfg), '') as paths:
        assert (Path(paths[0]) / 'alias.h').read_bytes() == (real / 'value.h').read_bytes()
        assert not (Path(paths[0]) / 'alias.h').is_symlink()
    (real / 'cycle').symlink_to(real, target_is_directory=True)
    with pytest.raises(NetworkError, match='cyclic|cycle'):
        snapshot(tmp_path, cfg)


@pytest.mark.parametrize('limit,value', [('MAX_BYTES', 1), ('MAX_FILE', 1), ('MAX_FILES', 0),
                                        ('MAX_NODES', 1), ('MAX_ROOTS', 0), ('MAX_DEPTH', 0)])
def test_capture_limits_stop_before_a_partial_context_is_returned(tmp_path, monkeypatch, limit, value):
    folder = tmp_path / 'inc'
    folder.mkdir()
    (folder / 'value.h').write_text('authored header')
    monkeypatch.setattr(deps, limit, value)
    with pytest.raises(NetworkError, match='budget'):
        snapshot(tmp_path, config('inc'))


@pytest.mark.parametrize('damage', ['version', 'content', 'path', 'recipe', 'shape'])
def test_materialization_refuses_corrupt_or_different_contexts(tmp_path, damage):
    folder = tmp_path / 'inc'
    folder.mkdir()
    (folder / 'value.h').write_text('authored header')
    cfg = config('inc')
    before = copy.deepcopy(snapshot(tmp_path, cfg))
    bundle = before['inputs']['compiler_dependencies']
    if damage == 'version':
        bundle['version'] = True
    elif damage == 'content':
        bundle['directories'][0]['files'][0]['content'] = b'different bytes'
    elif damage == 'path':
        bundle['directories'][0]['files'][0]['path'] = '../escape.h'
    elif damage == 'recipe':
        cfg = config('other')
    else:
        bundle['directories'] = None
    with pytest.raises(deps.DependencyError):
        with context.materialize(before, compiler_settings(cfg), ''):
            pytest.fail('invalid context cannot reach the compiler')
    assert not (tmp_path / 'escape.h').exists()


@pytest.mark.parametrize('flags', [['-Iextra'], ['-I', 'extra'], ['@response'], ['-Wp,-Iextra'],
                                 ['--include=extra.h'], ['--peep-file', 'rules.peep']])
def test_uncaptured_additional_compiler_inputs_remain_unqualified(flags):
    assert context.extra_inputs({**config()['compiler'], 'flags': flags})


def test_recipe_budget_is_checked_before_traversing_many_unit_overrides(tmp_path, monkeypatch):
    monkeypatch.setattr(deps, 'MAX_RECIPES', 1)
    with pytest.raises(NetworkError, match='recipe budget'):
        snapshot(tmp_path, config(units={'bank000': {}}))


def test_file_and_directory_metadata_matches_ordinary_copy_inputs_and_cleans_up(tmp_path):
    import os
    import stat

    folder = tmp_path / 'include'
    folder.mkdir()
    header = folder / 'context.h'
    header.write_text('authored header\n')
    os.utime(header, ns=(1_000_000_000, 1_000_000_000))
    header.chmod(0o444)
    folder.chmod(0o555)
    cfg = config('include')
    before = snapshot(tmp_path, cfg)
    with context.materialize(before, compiler_settings(cfg), '') as paths:
        copied = Path(paths[0]) / 'context.h'
        assert stat.S_IMODE(copied.stat().st_mode) == stat.S_IMODE(header.stat().st_mode)
        assert copied.stat().st_mtime_ns == header.stat().st_mtime_ns
        assert stat.S_IMODE(Path(paths[0]).stat().st_mode) == stat.S_IMODE(folder.stat().st_mode)
    assert not Path(paths[0]).exists()
    assert snapshot(tmp_path, cfg) == before  # Capturing does not invalidate itself through access times.
    folder.chmod(0o755)
