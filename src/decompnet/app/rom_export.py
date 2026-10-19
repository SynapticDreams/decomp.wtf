"""ROM export orchestration and bounded last-attempt state, outside the engine."""
import json
import time
from pathlib import Path

from ..network import NetworkError
from . import sms_export_state


def export(net, slug, log=print, translation_units=None, *, strict_documented=False):
    if type(strict_documented) is not bool:
        raise NetworkError('strict_documented must be a boolean')
    proj = net._project(slug)
    cfg = net.cfg(proj)
    sms = cfg.get('platform') in ('sms', 'gg') and not net.fork_slug(slug)
    if strict_documented and not sms:
        raise NetworkError('strict documented-source export is for local SMS/GG projects')
    if net.fork_slug(slug):
        return {'path': proj['root'], 'identical': None}
    from ..rom.export import export_rom
    from ..rom.export_gb import export_gb
    from ..rom.export_gba import export_gba
    from ..rom.export_nes import export_nes
    from ..rom.export_sms import export_sms

    if cfg.get('mapping'):
        raise NetworkError('mapping v1 supports fixed-extent disc export; a complete source-tree export is not supported yet')
    platform = cfg.get('platform')
    if translation_units is not None and platform != 'psx':
        raise NetworkError('translation-unit export groups currently support PS1 projects')
    exporter = export_gba if platform == 'gba' else export_gb if platform in ('gb', 'gbc') else \
        export_sms if sms else export_nes if platform == 'nes' else export_rom
    kwargs = {'translation_units': translation_units} if translation_units is not None else {}
    if sms:
        kwargs['strict_documented'] = strict_documented
    before = sms_export_state.stamp(net, proj) if sms else None
    try:
        result = exporter(net, slug, Path(proj['root']) / 'source', log=log, **kwargs)
    except Exception:
        if sms:
            failed = {'version': 1, 'passed': False, 'receipt_valid': False, 'errors': ['export_failed_before_receipt'],
                      'input': {'verified': False}, 'image': {'checked': False, 'equal': None},
                      'build': {'input': {'verified': False}, 'image': {'equal': False},
                                'process': {'completed': False, 'stage': 'export'},
                                'documented': {'routines': [], 'required': strict_documented}}}
            save(net, proj, {'path': str(Path(proj['root']) / 'source'), 'identical': False,
                 'verification': failed}, before, False)
        raise
    coherent = before == sms_export_state.stamp(net, proj) if sms else True
    save(net, proj, result, before, coherent)
    return result


def save(net, proj, result, context, coherent):
    with net.store.tx() as db:
        cfg = json.loads(db.execute('SELECT config FROM projects WHERE id=?', (proj['id'],)).fetchone()['config'])
        saved = {'t': time.time(), 'path': str(result['path']), 'identical': result.get('identical'),
                 'matched': result.get('matched'), 'functions': result.get('functions'),
                 'fallback': len(result.get('fallback') or []), 'documented': result.get('documented'),
                 'left_out': len(result.get('left_out') or [])}
        if 'verification' in result:
            coherent = coherent and context == sms_export_state.stamp(net, proj)
            saved['verification'] = sms_export_state.summary(result['verification'], context, coherent,
                                                            fallback=result.get('left_out') or [])
        cfg['export'] = saved
        db.execute('UPDATE projects SET config=? WHERE id=?', (json.dumps(cfg), proj['id']))
    net._progress_cache.pop(proj['id'], None)
