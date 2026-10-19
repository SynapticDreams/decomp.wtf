"""Worker research tools preserve text-only legacy notes and expose no review or detach authority."""
import json


def note(net, agent, slug, text='', function='', notes='', **options):
    result = net.add_note(agent, slug, text or notes, function or None, **options)
    return result if isinstance(result, str) else json.dumps(result, ensure_ascii=False)


def symbol(net, agent, slug, symbol, **options):
    return json.dumps(net.annotate_symbol(agent, slug, symbol, **options), ensure_ascii=False)


def inspect(net, agent, slug, kind='note', key=None, before_id=None, after_symbol=None, limit=50):
    return json.dumps(net.inspect_annotations(slug, kind, key, before_id=before_id, after_symbol=after_symbol, limit=limit), ensure_ascii=False)


def schemas():
    st = lambda description: {'type': 'string', 'description': description}
    metadata = {'annotation': {'type': 'object', 'description': 'version 1 annotation; optional for prose-only evidence'},
                'evidence': {'type': 'object', 'description': 'version 1 pending evidence; caller review receipts are refused'},
                'apply': {'type': 'boolean', 'description': 'preview false, then apply true with expected_plan'},
                'expected_plan': st('exact preview fingerprint')}
    return {
        'add_note': ('Leave a note. SMS/GG optional metadata binds full subject/revision/context without inventing RAM contents. '
                     'Use apply=false to preview and apply=true with expected_plan. Metadata stays pending operator review.',
                     {'type': 'object', 'properties': {'text': st('note text'), 'function': st('optional attachment'),
                         'note_id': {'type': 'integer', 'description': 'attach/replace metadata on an existing immutable note'},
                         **metadata}, 'required': []}),
        'annotate_symbol': ('Attach or replace SMS/GG symbol research using preview/application. This does not rename a '
                            'symbol, approve a purpose or affect discovery. Original metadata remains recoverable.',
                            {'type': 'object', 'properties': {'symbol': st('existing exact symbol name'), **metadata},
                             'required': ['symbol']}),
        'inspect_annotations': ('Inspect note/symbol research, original archived subjects and evidence. Omit key for a page. '
                                'Use next_before for notes and next_symbol for symbols; workers cannot review metadata.',
                                {'type': 'object', 'properties': {'kind': st('note | symbol'),
                                    'key': {'anyOf': [{'type': 'integer'}, {'type': 'string'}]}, 'before_id': {'type': 'integer'},
                                    'after_symbol': st('symbol page cursor'), 'limit': {'type': 'integer'}}, 'required': []})}
