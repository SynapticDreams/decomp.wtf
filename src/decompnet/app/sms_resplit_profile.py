"""Proposed mapping is analyzed privately; only resplit's guarded transaction may persist it."""
from __future__ import annotations

import json
from pathlib import Path

from ..network import NetworkError
from ..rom import sms_identity, sms_profile
from .sms_profile_proposal import prepare


def propose(proj, cfg, before, payload, apply, expected_plan):
    if payload is None:
        return cfg, before, {}
    if before is None or cfg.get('platform') not in ('sms', 'gg') or cfg.get('kind') != 'rom' or cfg.get('link'):
        raise NetworkError('profile migration is for local SMS/GG ROM projects')
    if not isinstance(payload, dict) or set(payload) != {'mapper', 'variant', 'reason'}:
        raise NetworkError('profile migration needs only mapper, variant and reason')
    if apply and expected_plan is None:
        raise NetworkError('preview this profile migration before applying it')
    image = sms_identity.strip_copier_header((Path(proj['root']) / cfg['rom']['file']).read_bytes())
    proposed = prepare(cfg, image, payload['mapper'], payload['variant'], payload['reason'], before['tables']['functions'])
    try:
        sms_profile.require_supported(proposed)
    except ValueError as exc:
        raise NetworkError(str(exc)) from None
    # Frozen work/dependencies remain original; only the configuration seen by the judge is proposed.
    source_state = {**before, 'project': {**before['project'], 'config': json.dumps(proposed)}}
    report = {'profile_transition': {'before': sms_profile.read(cfg), 'proposed': sms_profile.read(proposed)}}
    return proposed, source_state, report
