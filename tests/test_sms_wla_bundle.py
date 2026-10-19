"""Private immutable source bundles bind raw bytes, declared geometry and normalized revision."""
import base64
import hashlib
import json

import pytest

from decompnet.rom import wla_bundle
from .sms_wla_fixture import layout_for

IMAGE = b'\xff' * 0xC000
RAW = b'\xef\xbb\xbf; private comment\r\n[labels]\r\n01:2100 First\r\n01:2100 Alias\r\n'


def test_published_bundle_preserves_exact_raw_bytes_and_normalized_aliases(tmp_path):
    prepared = wla_bundle.prepare(RAW, layout_for(IMAGE), IMAGE)
    reference = wla_bundle.publish(tmp_path, prepared)
    assert wla_bundle.publish(tmp_path, prepared) == reference
    payload = json.loads(wla_bundle.verified(tmp_path, reference))
    assert base64.b64decode(payload['source']) == RAW
    loaded = wla_bundle.load(tmp_path, reference, IMAGE)
    assert loaded.names == {(0, 0x2100): 'First'}
    assert loaded.report['aliases'][0]['names'] == ['First', 'Alias']
    assert loaded.report['source']['sha256'] == hashlib.sha256(RAW).hexdigest()
    assert 'private comment' not in str(loaded.report)


def test_missing_layout_preserves_records_without_effective_names_or_seeds(tmp_path):
    prepared = wla_bundle.prepare(RAW, None, IMAGE)
    reference = wla_bundle.publish(tmp_path, prepared)
    loaded = wla_bundle.load(tmp_path, reference, IMAGE)
    assert not loaded.names and not loaded.seeds
    assert loaded.report['state'] == 'requires_layout' and len(loaded.report['records']) == 2
    assert all(row['status'] == 'requires_layout' for row in loaded.report['records'])


@pytest.mark.parametrize('change', ['different_input', 'modified', 'missing', 'reference', 'version', 'source_hash', 'directory_link', 'file_link'])
def test_changed_or_unavailable_bundle_cannot_be_reinterpreted(tmp_path, change):
    prepared = wla_bundle.prepare(RAW, layout_for(IMAGE), IMAGE)
    reference = wla_bundle.publish(tmp_path, prepared)
    path = wla_bundle.path(tmp_path, reference)
    image = IMAGE
    if change == 'different_input': image = IMAGE[:-1] + b'\0'
    elif change == 'modified': path.write_bytes(path.read_bytes() + b' ')
    elif change == 'missing': path.unlink()
    elif change == 'reference': reference['bundle_sha256'] = '../other'
    elif change == 'version': reference['version'] = 2
    elif change == 'source_hash': reference['source_sha256'] = '0' * 64
    else:
        if not hasattr(path, 'symlink_to'):
            return
        target = tmp_path / 'external'
        try:
            if change == 'file_link':
                path.rename(target); path.symlink_to(target)
            else:
                path.parent.rename(target); path.parent.symlink_to(target, target_is_directory=True)
        except OSError:
            return
    with pytest.raises((OSError, ValueError)):
        wla_bundle.load(tmp_path, reference, image)


def test_unknown_source_version_is_inspectable_without_effective_symbols(tmp_path):
    raw = b'[information]\nversion 4\n[labels]\n01:2100 First\n'
    prepared = wla_bundle.prepare(raw, layout_for(IMAGE), IMAGE)
    reference = wla_bundle.publish(tmp_path, prepared)
    loaded = wla_bundle.load(tmp_path, reference, IMAGE)
    assert loaded.report['state'] == 'unsupported_symbol_version'
    assert not loaded.names and not loaded.seeds


def test_corrupt_existing_bundle_is_never_overwritten_on_publication(tmp_path):
    prepared = wla_bundle.prepare(RAW, layout_for(IMAGE), IMAGE)
    reference = wla_bundle.publish(tmp_path, prepared)
    path = wla_bundle.path(tmp_path, reference)
    path.write_bytes(b'changed')
    with pytest.raises(ValueError, match='changed'):
        wla_bundle.publish(tmp_path, prepared)
    assert path.read_bytes() == b'changed'


def test_bundle_size_budget_is_enforced_before_publication(monkeypatch):
    monkeypatch.setattr(wla_bundle, 'MAX_BUNDLE', 10)
    with pytest.raises(ValueError, match='bundle exceeds'):
        wla_bundle.prepare(RAW, None, IMAGE)
