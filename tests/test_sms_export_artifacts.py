"""Export-tree provenance is bounded and distinct from generated scratch files."""
import os

import pytest

from decompnet.rom import export_sms_artifacts as artifacts


def test_source_edits_and_measured_outputs_change_fingerprint_but_scratch_files_do_not(tmp_path):
    (tmp_path / 'build.py').write_text('authored build')
    baseline = artifacts.fingerprint(tmp_path)
    scratch = tmp_path / 'build' / 'disassembly'
    scratch.mkdir(parents=True)
    (scratch / 'generated.asm').write_text('generated fixture')
    (tmp_path / 'build' / 'game.sms').write_bytes(b'authored result')
    assert artifacts.fingerprint(tmp_path) == baseline
    checked = artifacts.fingerprint(tmp_path, outputs=True)
    assert checked != baseline
    (scratch / 'generated.asm').write_text('edited scratch gets regenerated on build')
    assert artifacts.fingerprint(tmp_path, outputs=True) == checked
    (tmp_path / 'build' / 'game.sms').write_bytes(b'different')
    assert artifacts.fingerprint(tmp_path, outputs=True) != checked
    (tmp_path / 'build.py').write_text('different build')
    assert artifacts.fingerprint(tmp_path) != baseline


def test_caps_and_nonregular_inputs_cannot_be_attested(tmp_path, monkeypatch):
    (tmp_path / 'file').write_bytes(b'authored')
    data, info = artifacts.read_regular(tmp_path / 'file', 2)
    assert data == b'au' and info.st_size == 8
    with monkeypatch.context() as limited:
        limited.setattr(artifacts, 'MAX_BYTES', 1)
        assert artifacts.fingerprint(tmp_path) is None
    (tmp_path / 'second').write_bytes(b'authored')
    with monkeypatch.context() as limited:
        limited.setattr(artifacts, 'MAX_FILES', 1)
        assert artifacts.fingerprint(tmp_path) is None
    if hasattr(os, 'mkfifo'):
        os.mkfifo(tmp_path / 'special')
        assert artifacts.fingerprint(tmp_path) is None
        with pytest.raises(ValueError, match='regular_file'):
            artifacts.read_regular(tmp_path / 'special', 2)


def test_symlinks_including_the_output_directory_are_not_followed(tmp_path):
    source, private = tmp_path / 'export', tmp_path / 'private'
    source.mkdir(); private.mkdir()
    (private / 'game.sms').write_bytes(b'private fixture')
    try:
        (source / 'build').symlink_to(private, target_is_directory=True)
    except (OSError, NotImplementedError):
        assert artifacts.fingerprint(source) is not None  # Native symlink creation is unavailable on this host.
        return
    assert artifacts.fingerprint(source, outputs=True) is None
    (source / 'build').unlink()
    (source / 'header').symlink_to(private / 'game.sms')
    assert artifacts.fingerprint(source) is None
    with pytest.raises((OSError, ValueError)):
        artifacts.read_regular(source / 'header', 2)


def test_paths_and_permissions_are_framed_unambiguously(tmp_path):
    path = tmp_path / 'a'
    path.write_bytes(b'authored')
    path.chmod(0o600)
    before = artifacts.fingerprint(tmp_path)
    renamed = tmp_path / 'a1'
    path.rename(renamed)
    renamed.chmod(0o640)
    assert artifacts.fingerprint(tmp_path) != before
