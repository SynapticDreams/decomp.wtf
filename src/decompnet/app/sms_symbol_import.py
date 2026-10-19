"""Project-bound WLA previews, private source publication and bounded inspection."""
import base64
from collections import Counter
from contextlib import nullcontext
import hashlib
import json
from pathlib import Path
import re
import time

from ..network import NetworkError
from ..rom import sms_identity, sms_symbol_sources, wla_bundle, wla_symbols
from ..rom.export_sms_artifacts import read_regular
from .sms_export_state import stamp


def project(net, slug, *, write=False):
    proj = net._project(slug)
    cfg = net.cfg(proj)
    if cfg.get('platform') not in ('sms', 'gg') or cfg.get('kind') != 'rom' or net.fork_slug(slug) or (write and slug in net.links):
        raise NetworkError('declared symbol sources are for local SMS/GG ROM projects')
    return proj, cfg


def snapshot(net, slug, *, write=False):
    with net.store.lock:
        with (nullcontext() if net.store.conn.in_transaction else net.store.tx()):
            proj, cfg = project(net, slug, write=write)
            return proj, cfg, stamp(net, proj)


def image(proj, cfg):
    rom = cfg['rom']
    if rom.get('identity') is None and not re.fullmatch('[0-9a-f]{40}', str(rom.get('sha1') or '')):
        raise ValueError('frozen SMS/GG input identity is unavailable')
    raw, info = read_regular(Path(proj['root']) / rom['file'], int(rom['size']) + 513)
    if info.st_size > int(rom['size']) + 512:
        raise ValueError('original SMS/GG input size differs')
    result = sms_identity.strip_copier_header(raw)
    sms_identity.verify_normalized(result, rom.get('identity'), rom.get('sha1'))
    return result


def filename(name):
    return re.sub('[^A-Za-z0-9_. -]', '_', str(name).replace('\\', '/').rsplit('/', 1)[-1])[:128] or 'symbols.sym'


def page(prepared, name, offset=0):
    report, rows = prepared.report, prepared.report['records']
    records = [{**row, 'coordinates': row['coordinates'][:32], 'coordinate_count': len(row['coordinates']),
                'coordinates_truncated': len(row['coordinates']) > 32} for row in rows[offset:offset + 50]]
    return {'format': 'wla-bundle', 'from': filename(name), 'source': report['source'], 'state': report['state'],
            'source_id': prepared.sha256, 'input': report['input'], 'names': len(prepared.names), 'blocks': 0,
            'seeds': len(prepared.seeds), 'record_count': len(rows), 'counts': dict(Counter(r['status'] for r in rows)),
            'alias_count': sum(max(0, len(a['names']) - 1) for a in report['aliases']),
            'records': records, 'offset': offset, 'next_offset': offset + 50 if offset + 50 < len(rows) else None,
            'semantic_approval': False}


def import_source(net, slug, text, name, *, layout=None, apply=True, expected_plan=None, source_base64=None, offset=0):
    proj, cfg, before = snapshot(net, slug, write=True)
    if type(apply) is not bool or (expected_plan is not None and
            (not isinstance(expected_plan, str) or not re.fullmatch('[0-9a-f]{64}', expected_plan))):
        raise NetworkError('invalid symbol apply flag or preview fingerprint')
    if type(offset) is not int or not 0 <= offset <= wla_symbols.MAX_RECORDS or (apply and offset != 0):
        raise NetworkError('symbol preview offset is invalid')
    if offset and expected_plan is None:
        raise NetworkError('symbol preview pages require the preview fingerprint')
    try:
        original = image(proj, cfg)
        if source_base64 is not None:
            if text or not isinstance(source_base64, str) or len(source_base64) > 4 * ((wla_symbols.MAX_BYTES + 2) // 3):
                raise ValueError('supply one bounded symbol source')
            raw = base64.b64decode(source_base64, validate=True)
        elif isinstance(text, str) and len(text) <= wla_symbols.MAX_BYTES:
            raw = text.encode('utf-8')
        else:
            raise ValueError('supply a bounded UTF-8 symbol source')
        prepared = wla_bundle.prepare(raw, layout, original, mapper=net.sms.model(proj).kind)
        plan = hashlib.sha256(json.dumps([before, prepared.sha256, filename(name)]).encode()).hexdigest()
        if expected_plan is not None and expected_plan != plan:
            raise NetworkError('symbol preview is stale; preview again before applying')
        result = {'plan': plan, 'applied': apply, 'kept': len(prepared.report['records']),
                  'dropped': prepared.report['ignored_lines'], 'renamed': 0,
                  'symbol_file': page(prepared, name, offset)}
        if not apply:
            return result
        with net.store.tx() as db:
            if before != stamp(net, proj) or original != image(proj, cfg):
                raise NetworkError('project work or input changed during symbol import; preview again')
            current = json.loads(db.execute('SELECT config FROM projects WHERE id=?', (proj['id'],)).fetchone()['config'])
            reference = wla_bundle.publish(Path(proj['root']), prepared)
            current['symbol_file'] = {**reference, 'source_sha256': prepared.report['source']['sha256'],
                                      'from': filename(name), 'at': time.time()}
            db.execute('UPDATE projects SET config=? WHERE id=?', (json.dumps(current), proj['id']))
        net._progress_cache.pop(proj['id'], None)
        return result
    except (OSError, ValueError, TypeError, KeyError):
        raise NetworkError('symbol source, declared layout or original input is unavailable, invalid or differs') from None


def inspect(net, slug, *, offset=0, expected_source=None, expected_context=None):
    proj, cfg, context = snapshot(net, slug)
    if type(offset) is not int or not 0 <= offset <= wla_symbols.MAX_RECORDS:
        raise NetworkError('symbol inspection offset is invalid')
    if offset and (expected_source is None or expected_context is None):
        raise NetworkError('symbol inspection pages require source and context fingerprints')
    if expected_context is not None and expected_context != context:
        raise NetworkError('symbol inspection context changed; inspect the current source again')
    reference = cfg.get('symbol_file')
    if reference is None:
        reference = {}
    if not isinstance(reference, dict):
        raise NetworkError('stored symbol source metadata is invalid')
    try:
        path = (Path(proj['root']) / cfg['rom']['file']).with_suffix('.sym')
        prepared = sms_symbol_sources.select(path, image(proj, cfg),
                    reference=reference if 'format' in reference else None, mapper=net.sms.model(proj).kind, root=Path(proj['root']))
        if prepared is None:
            raise NetworkError('no active symbol source to inspect')
        if expected_source is not None and expected_source != prepared.sha256:
            raise NetworkError('symbol source changed; inspect the current source again')
        if context != stamp(net, proj):
            raise NetworkError('symbol inspection context changed; inspect the current source again')
        result = page(prepared, reference.get('from') or path.name, offset)
        result['inspection_context'] = context
        if reference.get('format') != 'wla-bundle':
            result['format'] = 'adjacent'
        if reference.get('notice'):
            result['notice'] = reference['notice']
        return result
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        raise NetworkError('symbol source is unavailable, changed, or needs a declared import') from None


def present(net, slug):
    proj, cfg = project(net, slug)
    reference = cfg.get('symbol_file')
    if reference is None:
        reference = {}
    if not isinstance(reference, dict):
        return {'format': 'unknown', 'from': 'symbols.sym', 'names': 0, 'blocks': 0, 'state': 'unavailable'}
    if reference.get('format') == 'disabled' and reference.get('state') != 'rejected':
        return None
    path = (Path(proj['root']) / cfg['rom']['file']).with_suffix('.sym')
    if 'format' not in reference and not path.exists():
        return None
    try:
        result = inspect(net, slug)
        return {key: value for key, value in result.items() if key not in ('records', 'offset', 'next_offset')}
    except NetworkError:
        return {'format': reference.get('format', 'adjacent'), 'from': filename(reference.get('from') or path.name),
                'names': 0, 'blocks': 0, 'state': 'unavailable', 'error': 'stored symbol evidence is unavailable or differs'}


def remove(net, slug):
    proj, _cfg = project(net, slug, write=True)
    net._update_cfg(slug, lambda cfg: cfg.update(symbol_file={'format': 'disabled'}))
    net._progress_cache.pop(proj['id'], None)
    return net.corrections(slug)
