"""Guarded metadata writes on existing notes/symbols; original metadata survives replacement."""
import time

from ..network import NetworkError
from ..rom.annotations import dump
from . import annotation_archives as archives, annotation_keys as keys, annotation_proofs as proofs
from . import annotation_subjects as subjects, annotation_views as views, sms_annotation_context as context


def note(net, proj, text, function, note_id):
    if note_id is not None:
        row = dict(keys.fetch(net, proj, 'note', note_id))
        if text and text != row['text']:
            raise ValueError('metadata edits do not rewrite original note text; create a new note')
        if function and net._function(function, proj['slug'])['id'] != row['function_id']:
            raise ValueError('metadata edits do not change the original note attachment')
        return row
    if not isinstance(text, str) or not text.strip() or len(text) > 4000:
        raise ValueError('note text must contain 1 to 4000 characters')
    fn = net._function(function, proj['slug']) if function else None
    return {'id': None, 'project_id': proj['id'], 'function_id': fn['id'] if fn else None,
            'text': text.strip(), 'annotation': None, 'evidence': None, 'subject': None}


def put(net, agent, slug, kind, key=None, *, text='', function=None, annotation=None, evidence=None,
        apply=False, expected_plan=None):
    if type(apply) is not bool:
        raise NetworkError('apply must be a boolean')
    try:
        with context.read(net):
            bound = context.load(net, slug)
            proj, cfg = bound[:2]
            if kind not in keys.TABLES:
                raise ValueError('research subject kind is note or symbol')
            row = note(net, proj, text, function, key) if kind == 'note' else dict(keys.fetch(net, proj, kind, key))
            if kind == 'note' and archives.archived(row['text']):
                raise ValueError('archived original subjects are read-only; create a new bound proposal')
            saved = subjects.descriptor(subjects.entity(net, kind, row), annotation, bound)
            subjects.validate(saved)
            proof = proofs.bind(evidence, agent, bound[3], bound[4], context.digest(saved))
            request = {'kind': kind, 'key': key, 'entity': saved['entity'],
                       'annotation': dump(annotation) if annotation is not None else None,
                       'evidence': dump(proof), 'subject': dump(saved), 'agent_id': agent.id}
            work = context.guard(net, proj)
            plan = context.plan(work, request)
        context.check_plan(expected_plan, plan, required=apply)
        proposed = {**row, **{field: request[field] for field in ('annotation', 'evidence', 'subject')}}
        if not apply:
            return {'applied': False, 'plan': plan, 'record': views.describe(net, kind, proposed, cfg, bound, full=True)}
        with net.store.tx() as db:
            context.current(net, slug, work, bound[3], bound[4])
            if kind == 'note' and key is None:
                key = db.execute('INSERT INTO notes(project_id,function_id,agent_id,text,created_at) VALUES(?,?,?,?,?)',
                                  (proj['id'], row['function_id'], agent.id, row['text'], time.time())).lastrowid
            else:
                archives.save(db, kind, row, 'research metadata replaced')
            column = 'id' if kind == 'note' else 'name'
            db.execute(f'UPDATE {keys.TABLES[kind]} SET annotation=?,evidence=?,subject=? WHERE project_id=? AND {column}=?',
                       (request['annotation'], request['evidence'], request['subject'], proj['id'], key))
            net._event(db, proj['id'], agent.id, 'annotation', f'pending {kind} research')
            updated = keys.fetch(net, proj, kind, key)
        net._progress_cache.pop(proj['id'], None)
        return {'applied': True, 'plan': plan, 'record': views.describe(net, kind, updated, cfg, bound, full=True)}
    except (ValueError, TypeError, KeyError, RecursionError, OverflowError) as exc:
        raise NetworkError(f'invalid research annotation: {exc}') from None
