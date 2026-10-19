"""Stable source identity for research context, independent of upload timestamps and display names."""
import base64
import hashlib
import json
from pathlib import Path

from ..rom import sms_symbol_sources, wla_bundle, wla_symbols


def adjacent(proj, cfg):
    path = (Path(proj['root']) / cfg['rom']['file']).with_suffix('.sym')
    try:
        raw = sms_symbol_sources.source_bytes(path)
    except FileNotFoundError:
        return None
    return {'format': 'unqualified-adjacent', 'source_sha256': hashlib.sha256(raw).hexdigest(), 'size': len(raw)}


def binding(proj, cfg, revision):
    reference = cfg.get('symbol_file')
    if reference is None or isinstance(reference, dict) and 'format' not in reference:
        return adjacent(proj, cfg)
    if not isinstance(reference, dict):
        raise ValueError('symbol source reference is invalid')
    if reference.get('format') == 'disabled':
        return adjacent(proj, cfg) if reference.get('state') == 'rejected' else {'format': 'disabled'}
    value = json.loads(wla_bundle.verified(Path(proj['root']), reference))
    expected = {key: revision[key] for key in ('size', 'sha256')}
    if not isinstance(value, dict) or set(value) != {'version', 'input', 'source', 'layout'} or \
            type(value['version']) is not int or value['version'] != 1 or value['input'] != expected:
        raise ValueError('symbol source revision or format differs')
    if not isinstance(value['source'], str) or len(value['source']) > 4 * ((wla_symbols.MAX_BYTES + 2) // 3):
        raise ValueError('symbol source exceeds its encoding budget')
    raw = base64.b64decode(value['source'], validate=True)
    if len(raw) > wla_symbols.MAX_BYTES:
        raise ValueError('symbol source exceeds its byte budget')
    sha = hashlib.sha256(raw).hexdigest()
    if reference.get('source_sha256') is not None and reference['source_sha256'] != sha:
        raise ValueError('symbol source identity differs')
    return {'format': 'wla-bundle', 'version': 1, 'bundle_sha256': reference['bundle_sha256'], 'source_sha256': sha}
