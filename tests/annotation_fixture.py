"""Authored research records for schema, persistence and later consumer qualification."""
import copy

SIZE = 0x10000


def annotation(kind='record'):
    specs = {
        'code': (1, {}), 'noreturn': (1, {}), 'data': (16, {'encoding': 'bytes'}),
        'table': (8, {'count': 4}), 'operands': (1, {'bytes_after_call': 2}),
        'record': (64, {'count': 4, 'stride': 16, 'overlap': 'reject', 'fields': [
            {'name': 'flags', 'offset': 0, 'type': 'bits', 'width': 1, 'endian': 'little',
             'bits': [{'name': 'active', 'lsb': 0, 'width': 1}, {'name': 'mode', 'lsb': 2, 'width': 2}]},
            {'name': 'handler', 'offset': 2, 'type': 'ptr16le', 'target': 'code',
             'bank': {'offset': 4, 'width': 1, 'meaning': 'physical', 'source_sha256': None}},
            {'name': 'bank', 'offset': 4, 'type': 'u8'}, {'name': 'health', 'offset': 5, 'type': 's8'}]}),
        'pointers': (32, {'count': 4, 'stride': 8, 'pointer_offset': 2, 'encoding': 'u16le', 'target': 'code',
                         'bank': {'offset': 0, 'width': 1, 'meaning': 'register', 'source_sha256': None}}),
        'split_pointers': (32, {'count': 4, 'stride': 1, 'low_offset': 0, 'high_offset': 8, 'target': 'code',
                               'bank': {'offset': 16, 'width': 1, 'meaning': 'physical', 'source_sha256': None}}),
        'number': (2, {'value': 0xC000, 'endian': 'little'}),
        'mapping': (16, {'when': {'banks': [0, 1, None], 'cartridge': True},
                         'facts': {'banks': [None, None, 5], 'control': 8, 'control_known': 8}}),
    }
    size, spec = specs[kind]
    return {'version': 1, 'kind': kind, 'target': {'space': 'rom', 'offset': 0x100, 'size': size}, 'spec': copy.deepcopy(spec)}


def evidence():
    return {'version': 1, 'revision': None, 'context': None, 'subject_sha256': None,
            'origin': {'kind': 'agent', 'ref': 'authored-agent'}, 'state': 'hypothesis', 'confidence': 'low',
            'alternatives': ['Another possible interpretation.'], 'links': [],
            'review': {'state': 'pending', 'actor': None, 'at': None, 'binding_sha256': None}}
