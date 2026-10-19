"""Existing operator correction endpoint: paged history, inspection, proposals and review."""
from ..network import NetworkError


def handle(net, slug, request, data):
    if request.method == 'GET':
        q = request.query_params
        if q.get('id') is not None:
            return net.inspect_correction(slug, int(q['id']))
        return net.corrections(slug, before_id=int(q['before_id']) if q.get('before_id') else None,
                               limit=int(q.get('limit', 500)))
    action = data.get('action', 'create')
    if action == 'inspect':
        return net.inspect_correction(slug, data.get('id'))
    if action == 'review':
        return net.review_correction(slug, data.get('id'), data.get('ok'),
                                     apply=data.get('apply', False), expected_plan=data.get('expected_plan'))
    if action != 'create':
        raise NetworkError('unknown correction action')
    if data.get('apply') is True and data.get('expected_plan') is None:
        raise NetworkError('preview the correction before applying')
    agent, _token = net.local_agent('you')
    return net.correct_split(agent, slug, data.get('kind'), data.get('at', ''), data.get('reason'),
                             data.get('count', 0), data.get('function', ''), annotation=data.get('annotation'),
                             evidence=data.get('evidence'), apply=data.get('apply', False), expected_plan=data.get('expected_plan'))
