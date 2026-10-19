"""One correction workflow for both MCP and built-in agents; operator review is deliberately absent."""
import json


def correct(net, agent, slug, kind, at='', reason='', count=0, function='', notes='', **options):
    result = net.correct_split(agent, slug, kind, at, reason or notes, count, function, **options)
    return result if isinstance(result, str) else json.dumps(result, ensure_ascii=False)


def inspect(net, agent, slug, correction_id=None, before_id=None, limit=50):
    result = net.inspect_correction(slug, correction_id) if correction_id is not None else \
        net.corrections(slug, before_id=before_id, limit=limit)
    return json.dumps(result, ensure_ascii=False)


def schemas():
    text = lambda description: {'type': 'string', 'description': description}
    return {
        'correct_split': ('Record a split correction. Existing data/code/table/operands/noreturn calls remain supported. '
                          'SMS/GG structured annotations support record/pointers/split_pointers/number/mapping too. '
                          'Use apply=false to preview, then apply=true with expected_plan. Structured facts remain '
                          'pending operator review; confidence never grants approval. See guide sms.',
                          {'type': 'object', 'required': ['kind', 'reason'], 'properties': {
                              'kind': text('annotation kind'), 'at': text('explicit function or NN:AAAA for legacy hint kinds'),
                              'reason': text('how you know, 20 to 1000 characters'), 'count': {'type': 'integer'},
                              'function': text('coordinate context'), 'annotation': {'type': 'object', 'description': 'version 1 annotation'},
                              'evidence': {'type': 'object', 'description': 'version 1 evidence; receipt fields must be unreviewed'},
                              'apply': {'type': 'boolean'}, 'expected_plan': text('fingerprint returned by preview')}}),
        'inspect_corrections': ('Inspect existing correction facts, evidence and application status. '
                                'Omit correction_id for a paged history; the result includes next_before.',
                                {'type': 'object', 'properties': {'correction_id': {'type': 'integer'},
                                    'before_id': {'type': 'integer'}, 'limit': {'type': 'integer'}}, 'required': []})}
