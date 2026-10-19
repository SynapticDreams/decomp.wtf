"""Preview and store bound correction claims; callers cannot grant their own review authority."""
import copy
import time

from ..network import NetworkError
from ..rom.annotations import dump, validate_annotation
from . import correction_policy as policy, sms_annotation_context as context, correction_views as views
from .annotation_proofs import hypothesis as hypothesis, bind


def legacy_annotation(net, slug, kind, at, count, function):
    proj, cfg = policy.project(net, slug, sms=True)
    flat, _cpu = net._banked_at(proj, at, function or None)
    size = policy.bounds(kind, flat, count, cfg['rom']['size'])
    spec = {'encoding': 'bytes'} if kind == 'data' else {'count': count} if kind == 'table' else \
        {'bytes_after_call': count} if kind == 'operands' else {}
    return {'version': 1, 'kind': kind, 'target': {'space': 'rom', 'offset': flat, 'size': size}, 'spec': spec}


def prepare(net, agent, slug, kind, at, reason, count, function, annotation, evidence):
    values = context.load(net, slug)
    proj, _cfg, original, revision, mapping = values
    validate_annotation(annotation, rom_size=len(original))
    if annotation['kind'] != kind or type(count) is not int or count != 0:
        raise ValueError('structured corrections take kind and count from their annotation; omit the legacy count')
    value = copy.deepcopy(annotation)
    flat, cpu = value['target']['offset'], None
    if at:
        placed, cpu = net._banked_at(proj, at, function or None)
        if placed != flat:
            raise ValueError('annotation and explicit location disagree')
    if kind in policy.KINDS and cpu is None:
        raise ValueError('legacy hint kinds require an explicit location')
    proof = bind(evidence, agent, revision, mapping, context.subject(value, cpu, original))
    return values, {'kind': kind, 'rom_offset': flat, 'cpu': cpu,
                    'count': value['spec'].get('count', value['spec'].get('bytes_after_call', value['target']['size'] if kind == 'data' else 0)),
                    'reason': policy.reason(reason), 'annotation': dump(value), 'evidence': dump(proof)}


def add(net, agent, slug, kind, at, reason, count, function, annotation, evidence, *, apply, expected_plan):
    if type(apply) is not bool:
        raise NetworkError('apply must be a boolean')
    try:
        if annotation is None:
            annotation = legacy_annotation(net, slug, kind, at, count, function)
            count = 0
        if evidence is None:
            evidence = hypothesis()
        with context.read(net):
            values, request = prepare(net, agent, slug, kind, at, reason, count, function, annotation, evidence)
            proj = values[0]
            work = context.guard(net, proj)
            plan = context.plan(work, {**request, 'agent_id': agent.id})
        context.check_plan(expected_plan, plan, required=apply)
        row = {**request, 'id': None, 'project_id': proj['id'], 'agent_id': agent.id, 'agent': agent.name,
               'created_at': None, 'undone_at': None}
        if not apply:
            return {'applied': False, 'plan': plan, 'correction': views.detail(net, row, values[1], values)}
        with net.store.tx() as db:
            context.current(net, slug, work, values[3], values[4])
            policy.rate(net, agent)
            now = time.time()
            columns = ('kind', 'rom_offset', 'cpu', 'count', 'reason', 'annotation', 'evidence')
            cid = db.execute(f"INSERT INTO corrections(project_id,agent_id,created_at,{','.join(columns)}) "
                             f"VALUES({','.join('?' for _ in range(3 + len(columns)))})",
                             (proj['id'], agent.id, now, *(request[key] for key in columns))).lastrowid
            row.update(id=cid, created_at=now)
            # Metadata belongs to its own correction row; plaintext notes cannot inherit approval.
            net._event(db, proj['id'], agent.id, 'correction', f'pending research correction {cid}: {kind}')
        net._progress_cache.pop(proj['id'], None)
        return {'applied': True, 'plan': plan, 'correction': views.detail(net, row, values[1], values)}
    except (ValueError, TypeError, KeyError, OverflowError, RecursionError) as exc:
        raise NetworkError(f'invalid structured correction: {exc}') from None
