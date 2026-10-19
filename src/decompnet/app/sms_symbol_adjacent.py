"""Bound initial sidecar copying and bind qualified geometry without implicit assembler-bank assumptions."""
import hashlib
import json
import time

from ..rom import sms_symbol_sources as sources, wla_bundle
from ..rom.export_sms_artifacts import read_regular
from .sms_symbol_import import filename

MAX_LAYOUT = 2 * 1024 * 1024


def copy(original, target, log):
    notice = {}
    for suffix, limit, key in (('.sym', 8 * 1024 * 1024, 'source'), ('.sym.layout.json', MAX_LAYOUT, 'layout')):
        try:
            raw, info = read_regular(original.with_suffix(suffix), limit + 1)
            if info.st_size > limit:
                raise ValueError('sidecar exceeds its read budget')
            target.with_suffix(suffix).write_bytes(raw)
        except FileNotFoundError:
            continue
        except (OSError, ValueError):
            notice[key] = 'unavailable'
            log(f'adjacent symbol {key} is unavailable or exceeds its budget; no labels accepted from it')
    return {'from': filename(original.with_suffix('.sym').name), 'issues': notice}


def initialize(path, image, notice, log):
    source = path.with_suffix('.sym')
    if not source.exists():
        return None
    raw = sources.source_bytes(source)
    declaration = None
    origin = (notice or {}).get('from') or filename(source.name)
    state = dict((notice or {}).get('issues', {}))
    try:
        raw_layout, info = read_regular(path.with_suffix('.sym.layout.json'), MAX_LAYOUT + 1)
        if info.st_size > MAX_LAYOUT:
            raise ValueError('layout exceeds its read budget')
        declaration = json.loads(raw_layout)
        if declaration is None:
            raise ValueError('a declaration must be an object')
    except FileNotFoundError:
        pass
    except (OSError, ValueError, RecursionError):
        state['layout'] = 'rejected'
    try:
        prepared = wla_bundle.prepare(raw, declaration, image)
    except (ValueError, TypeError, KeyError, RecursionError):
        state['source_or_layout'] = 'rejected'
        try:
            prepared = wla_bundle.prepare(raw, None, image)
        except (ValueError, TypeError, KeyError):
            log('adjacent symbol source is unqualified; its original bytes are retained without using labels')
            return {'format': 'disabled', 'state': 'rejected', 'from': origin,
                    'source_sha256': hashlib.sha256(raw).hexdigest(), 'notice': state}
    reference = wla_bundle.publish(path.parent, prepared)
    log(f"adjacent symbol source: {prepared.report['state']}; {len(prepared.seeds)} seed suggestions")
    return {**reference, 'source_sha256': prepared.report['source']['sha256'], 'from': origin,
            'at': time.time(), **({'notice': state} if state else {})}
