"""Pure, revision-bound cartridge declarations shared by profile saves and resplit proposals."""
from __future__ import annotations

import copy
import hashlib

from ..network import NetworkError
from ..rom import sms_identity, sms_profile


def bind_identity(cfg, image, functions):
    if cfg['rom'].get('identity') is not None:
        return
    for fn in functions:
        if fn['rom_offset'] is None:
            continue
        target = bytes(fn['target'] or b'')
        if fn['rom_offset'] < 0 or image[fn['rom_offset']:fn['rom_offset'] + len(target)] != target:
            raise NetworkError('legacy ROM differs from stored function targets; retain the original revision')
    cfg['rom']['identity'] = sms_identity.identify(image, image, {**cfg['rom'], 'platform': cfg['platform']})


def prepare(cfg, image, mapper, variant, reason, functions):
    if not isinstance(reason, str):
        raise NetworkError('profile reason must be text')
    if not isinstance(mapper, str) or not isinstance(variant, str):
        raise NetworkError('mapper and variant must be text')
    candidate = copy.deepcopy(cfg)
    try:
        sms_identity.verify_normalized(image, cfg['rom'].get('identity'), cfg['rom'].get('sha1'))
        sms_profile.read(cfg)
        bind_identity(candidate, image, functions)
        candidate['sms_profile'] = {'version': 1, 'mapper': mapper, 'variant': variant, 'origin': 'operator',
            'reason': ' '.join(reason.split()), 'sha256': hashlib.sha256(image).hexdigest(), 'size': len(image)}
        sms_profile.read(candidate)
        sms_profile.validate_model(candidate['sms_profile'])
    except (ValueError, TypeError) as exc:
        raise NetworkError(str(exc)) from None
    candidate.pop('export', None)
    return candidate
