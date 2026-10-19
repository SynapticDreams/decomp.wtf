"""Metadata actions extend existing note/symbol namespaces, with operator authority supplied by route guards."""
from ..network import NetworkError


def handle(net, slug, request, data, kind):
    if request.method == 'GET':
        q = request.query_params
        key = int(q['id']) if kind == 'note' and q.get('id') else q.get('symbol') if kind == 'symbol' else None
        return net.inspect_annotations(slug, kind, key, before_id=int(q['before_id']) if q.get('before_id') else None,
                                       after_symbol=q.get('after_symbol'), limit=int(q.get('limit', 50)))
    action = data.get('action', 'create' if kind == 'note' else 'annotate')
    key = data.get('id') if kind == 'note' else data.get('symbol')
    if action == 'inspect':
        return net.inspect_annotations(slug, kind, key)
    if action in ('review', 'clear'):
        return net.review_annotation(slug, kind, key, ok=data.get('ok'), clear=action == 'clear',
                                      apply=data.get('apply', False), expected_plan=data.get('expected_plan'))
    if action not in ('create', 'annotate'):
        raise NetworkError('unknown research annotation action')
    plain = kind == 'note' and action == 'create' and not any(
        name in data for name in ('annotation', 'evidence', 'apply', 'expected_plan', 'id'))
    if data.get('apply') is True and data.get('expected_plan') is None:
        raise NetworkError('preview research metadata before applying')
    agent, _token = net.local_agent('you')
    if plain:
        return {'message': net.add_note(agent, slug, str(data.get('text', '')).strip()[:2000], data.get('function') or None)}
    options = {'annotation': data.get('annotation'), 'evidence': data.get('evidence'),
               'apply': data.get('apply', False), 'expected_plan': data.get('expected_plan')}
    return net.add_note(agent, slug, data.get('text', ''), data.get('function'), note_id=key, **options) if kind == 'note' else \
        net.annotate_symbol(agent, slug, key, **options)
