"""Fixed-width fields, bitfields and explicit overlapping views inside strided records."""
from .fields import fields, integer, choice, sequence, text
from .pointers import pointer, intersects

WIDTHS = {'u8': 1, 's8': 1, 'u16le': 2, 's16le': 2, 'u16be': 2, 's16be': 2,
          'u32le': 4, 'u32be': 4, 's32le': 4, 's32be': 4}


def bitfields(value, width):
    names, occupied = set(), 0
    for field in sequence(value, 1, 32):
        fields(field, ('name', 'lsb', 'width'))
        name = text(field['name'], 64, identifier=True)
        low = integer(field['lsb'], 0, 8 * width - 1)
        count = integer(field['width'], 1, 8 * width)
        if low + count > 8 * width:
            raise ValueError('bitfield extends outside its storage')
        mask = ((1 << count) - 1) << low
        if name in names or occupied & mask:
            raise ValueError('duplicate or overlapping bitfield')
        names.add(name)
        occupied |= mask


def field(value, stride):
    if not isinstance(value, dict):
        raise ValueError('record field must be an object')
    kind = choice(value.get('type'), (*WIDTHS, 'bytes', 'bits', 'ptr16le', 'ptr16be'))
    extra = ('width',) if kind == 'bytes' else ('width', 'endian', 'bits') if kind == 'bits' else (
        'bank', 'target') if kind.startswith('ptr') else ()
    fields(value, ('name', 'offset', 'type', *extra))
    text(value['name'], 64, identifier=True)
    offset = integer(value['offset'], 0, stride - 1)
    if kind in WIDTHS:
        width = WIDTHS[kind]
    elif kind == 'bytes':
        width = integer(value['width'], 1, 65536)
    elif kind == 'bits':
        width = integer(value['width'], 1, 4)
        if width not in (1, 2, 4):
            raise ValueError('bitfield storage must be one, two or four bytes')
        choice(value['endian'], ('little', 'big'))
        bitfields(value['bits'], width)
    else:
        width = 2
        pointer(offset, value['bank'], stride)
        choice(value['target'], ('code', 'data', 'unknown'))
    if offset + width > stride:
        raise ValueError('record field extends outside its stride')
    return offset, width


def validate(spec, size):
    fields(spec, ('count', 'stride', 'fields', 'overlap'))
    count, stride = integer(spec['count'], 1, 4096), integer(spec['stride'], 1, 65536)
    policy = choice(spec['overlap'], ('reject', 'views'))
    if count * stride > size:
        raise ValueError('records extend outside their declared target')
    names, spans = set(), []
    for item in sequence(spec['fields'], 1, 256):
        span = field(item, stride)
        if item['name'] in names:
            raise ValueError('duplicate record field name')
        if policy == 'reject' and any(intersects(*span, *other) for other in spans):
            raise ValueError('record fields overlap without an explicit view policy')
        names.add(item['name'])
        spans.append(span)
