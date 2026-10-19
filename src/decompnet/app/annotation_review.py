"""Review or detach metadata on existing notes/symbols through the shared operator authority mechanism."""
import copy
import time

from ..network import NetworkError
from ..rom.annotations import dump, inspect
from ..rom.annotations.evidence import binding
from . import annotation_archives as archives, annotation_keys as keys, annotation_subjects as subjects
from . import annotation_views as views, sms_annotation_context as context
from . import annotation_records as records, correction_policy as policy
from .annotation_payloads import parse


def change(net, slug, kind, key, *, ok=None, clear=False, apply=False, expected_plan=None):
    if type(apply) is not bool or type(clear) is not bool or (not clear and type(ok) is not bool):
        raise NetworkError('review decision, clear and apply must be booleans')
    with context.read(net):
        if clear:
            proj, cfg = policy.project(net, slug, sms=True)
            bound = None
        else:
            bound = context.load(net, slug)
            proj, cfg = bound[:2]
        row = keys.fetch(net, proj, kind, key)
        if clear:
            bound = records.values(net, proj, [row])
        if kind == 'note' and archives.is_archive(row):
            raise NetworkError('archived original subjects are read-only')
        work = context.guard(net, proj)
        plan = context.plan(work, {'kind': kind, 'key': key, 'ok': ok, 'clear': clear})
        if not clear:
            annotation, evidence = parse(row, cfg['rom']['size'])
            subject = inspect(row['subject'], subjects.validate)
            if evidence.value is None or subject.value is None or row['annotation'] is not None and annotation.value is None:
                raise NetworkError('review requires supported annotation, evidence and subject metadata')
            try:
                valid = subjects.current(net, kind, row, annotation.value, evidence.value, subject.value, bound)
            except (ValueError, TypeError, KeyError):
                valid = False
            if not valid:
                raise NetworkError('research binding is stale; create a new bound proposal')
    context.check_plan(expected_plan, plan, required=apply)
    if not apply:
        return {'applied': False, 'plan': plan, 'record': views.describe(net, kind, row, cfg, bound, full=True),
                'decision': 'detach_metadata' if clear else 'accepted' if ok else 'rejected'}
    with net.store.tx() as db:
        if clear:
            current, _cfg = policy.project(net, slug, sms=True)
            if context.guard(net, current) != work:
                raise NetworkError('project work changed; preview again')
        else:
            context.current(net, slug, work, bound[3], bound[4])
        column = 'id' if kind == 'note' else 'name'
        if clear:
            archive_id = archives.save(db, kind, row, 'research metadata detached')
            db.execute(f'UPDATE {keys.TABLES[kind]} SET annotation=NULL,evidence=NULL,subject=NULL WHERE project_id=? AND {column}=?',
                       (proj['id'], key))
        else:
            proof = copy.deepcopy(evidence.value)
            proof['review'] = {'state': 'accepted' if ok else 'rejected', 'actor': 'operator',
                               'at': int(time.time()), 'binding_sha256': binding(proof)}
            db.execute(f'UPDATE {keys.TABLES[kind]} SET evidence=? WHERE project_id=? AND {column}=?', (dump(proof), proj['id'], key))
        updated = keys.fetch(net, proj, kind, key)
        if not clear:
            keys.record(net, db, kind, updated)
    net._progress_cache.pop(proj['id'], None)
    return {'applied': True, 'plan': plan, 'archive_id': archive_id if clear else None,
            'record': views.describe(net, kind, updated, cfg, bound, full=True)}
