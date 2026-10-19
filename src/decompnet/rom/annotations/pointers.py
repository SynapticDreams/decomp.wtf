"""Near, far and split-byte reference geometry; decoding/discovery is a separate consumer."""
from .fields import fields, integer, choice, digest


def bank(value, limit):
    if value is None:
        return None
    fields(value, ('offset', 'width', 'meaning', 'source_sha256'))
    offset = integer(value['offset'], 0, limit - 1)
    width = integer(value['width'], 1, 2)
    if offset + width > limit:
        raise ValueError('bank field extends outside its container')
    choice(value['meaning'], ('physical', 'register', 'assembler'))
    if value['meaning'] == 'assembler':
        digest(value['source_sha256'])
    elif value['source_sha256'] is not None:
        raise ValueError('only assembler bank identifiers select a source layout')
    return offset, width


def intersects(a, width, b, other_width):
    return a < b + other_width and b < a + width


def pointer(offset, bank_field, limit):
    offset = integer(offset, 0, limit - 1)
    if offset + 2 > limit:
        raise ValueError('pointer field extends outside its container')
    location = bank(bank_field, limit)
    if location and intersects(offset, 2, *location):
        raise ValueError('pointer and bank fields overlap')
    return offset


def validate(spec, size, *, split=False):
    names = ('count', 'stride', 'low_offset', 'high_offset', 'bank', 'target') if split else (
        'count', 'stride', 'pointer_offset', 'encoding', 'bank', 'target')
    fields(spec, names)
    count = integer(spec['count'], 1, 4096)
    stride = integer(spec['stride'], 1, 65536)
    choice(spec['target'], ('code', 'data', 'unknown'))
    if not split:
        choice(spec['encoding'], ('u16le', 'u16be'))
        pointer(spec['pointer_offset'], spec['bank'], stride)
        if count * stride > size:
            raise ValueError('pointer records extend outside the declared target')
        return
    low, high = (integer(spec[key], 0, size - 1) for key in ('low_offset', 'high_offset'))
    def aliases(a, b):
        return abs(a - b) % stride == 0 and abs(a - b) // stride < count
    if aliases(low, high):
        raise ValueError('split pointer arrays overlap')
    if max(low, high) + (count - 1) * stride + 1 > size:
        raise ValueError('split pointer arrays extend outside the declared target')
    location = bank(spec['bank'], size)
    if location:
        offset, width = location
        if offset + (count - 1) * stride + width > size or (count > 1 and width > stride):
            raise ValueError('split bank array extends outside its stride or target')
        if any(aliases(offset + byte, component) for byte in range(width) for component in (low, high)):
            raise ValueError('split bank and pointer arrays overlap')
