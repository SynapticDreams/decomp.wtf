"""Operator-only review of the existing correction record, guarded by the same preview/work identity."""
import copy
import time

from ..network import NetworkError
from ..rom.annotations import dump
from ..rom.annotations.evidence import binding
from . import correction_policy as policy, correction_receipts as receipts, correction_records as records
from . import correction_views as views, sms_annotation_context as context


def review(net, slug, cid, ok, *, apply=False, expected_plan=None):
    if type(ok) is not bool or type(apply) is not bool:
        raise NetworkError('review decision and apply must be booleans')
    with context.read(net):
        values = context.load(net, slug)
        proj, cfg = values[:2]
        row = records.one(net, proj, cid)
        work = context.guard(net, proj)
        plan = context.plan(work, {'review': cid, 'ok': ok})
        annotation, evidence = views.payloads(row, cfg['rom']['size'])
        if row['undone_at'] is not None or annotation.value is None or evidence.value is None:
            raise NetworkError('review requires a supported, active research record')
        try:
            views.geometry(row, annotation.value)
            if not context.validate_binding(annotation.value, evidence.value, row['cpu'], values):
                raise ValueError('stored revision, context or subject is stale')
            views.geometry(row, annotation.value, values)
        except (ValueError, TypeError, KeyError, NetworkError):
            raise NetworkError('correction binding is invalid or stale; create a new bound proposal') from None
        conflict = policy.conflict(net, proj['id'], row['kind'], row['rom_offset'], annotation.value['target']['size'])
    if ok and conflict:
        raise NetworkError(conflict)
    context.check_plan(expected_plan, plan, required=apply)
    if not apply:
        return {'applied': False, 'plan': plan, 'decision': 'accepted' if ok else 'rejected',
                'correction': views.detail(net, row, cfg, values)}
    with net.store.tx() as db:
        context.current(net, slug, work, values[3], values[4])
        proof = copy.deepcopy(evidence.value)
        proof['review'] = {'state': 'accepted' if ok else 'rejected', 'actor': 'operator',
                           'at': int(time.time()), 'binding_sha256': binding(proof)}
        db.execute('UPDATE corrections SET evidence=? WHERE project_id=? AND id=?', (dump(proof), proj['id'], cid))
        updated = records.one(net, proj, cid)
        receipts.record(net, db, updated)
    net._progress_cache.pop(proj['id'], None)
    return {'applied': True, 'plan': plan, 'correction': views.detail(net, updated, cfg, values)}
