"""Version 1 research payloads. These declarations never change code or mapping by themselves."""
from ..sms_mapping import BusState
from .codec import dump
from .fields import fields, integer, choice, version
from . import pointers, records

LEGACY = ('code', 'data', 'table', 'operands', 'noreturn')
KINDS = (*LEGACY, 'record', 'pointers', 'split_pointers', 'number', 'mapping')
BUS_FIELDS = {'banks', 'registers', 'control', 'control_known', 'cartridge', 'bios', 'wram', 'other_source', 'rom_modified'}


def target(value, rom_size):
    fields(value, ('space', 'offset', 'size'))
    space = choice(value['space'], ('rom', 'wram', 'cart_ram'))
    limit = rom_size if space == 'rom' else 0x2000 if space == 'wram' else 0x8000
    offset, size = integer(value['offset'], 0, limit - 1), integer(value['size'], 1, limit)
    if offset + size > limit:
        raise ValueError('annotation target extends outside its address space')
    return space, size


def bus(value):
    if not isinstance(value, dict) or not set(value) <= BUS_FIELDS:
        raise ValueError('unsupported scoped bus facts')
    converted = dict(value)
    for key in ('banks', 'registers'):
        if key in value:
            if not isinstance(value[key], list):
                raise ValueError('bus selections must be lists')
            converted[key] = tuple(value[key])
    try:
        BusState(**converted)
    except (ValueError, TypeError):
        raise ValueError('invalid scoped bus facts') from None


def validate(value, *, rom_size):
    dump(value)
    integer(rom_size, 0, 0x400000)
    fields(value, ('version', 'kind', 'target', 'spec'))
    version(value['version'])
    kind = choice(value['kind'], KINDS)
    space, size = target(value['target'], rom_size)
    spec = value['spec']
    if kind in LEGACY:
        if space != 'rom':
            raise ValueError('legacy split corrections target cartridge ROM')
        if kind in ('code', 'noreturn'):
            fields(spec, ())
            if size != 1:
                raise ValueError('entry annotations identify a single entry byte')
        elif kind == 'data':
            fields(spec, ('encoding',))
            choice(spec['encoding'], ('bytes', 'ascii', 'u8', 's8', 'u16le', 'u16be'))
            if spec['encoding'].startswith('u16') and size % 2:
                raise ValueError('word data requires whole words')
        elif kind == 'operands':
            fields(spec, ('bytes_after_call',))
            integer(spec['bytes_after_call'], 1, 8)
            if size != 1:
                raise ValueError('operand annotations identify a callee entry byte')
        else:
            fields(spec, ('count',))
            if size != 2 * integer(spec['count'], 1, 128):
                raise ValueError('legacy table extent differs from its dense word count')
    elif kind == 'record':
        records.validate(spec, size)
    elif kind in ('pointers', 'split_pointers'):
        pointers.validate(spec, size, split=kind == 'split_pointers')
    elif kind == 'number':
        fields(spec, ('value', 'endian'))
        choice(spec['endian'], ('little', 'big'))
        if size not in (1, 2, 3, 4):
            raise ValueError('numeric annotations occupy one to four bytes')
        integer(spec['value'], 0, (1 << (8 * size)) - 1)
    else:
        fields(spec, ('when', 'facts'))
        if space != 'rom':
            raise ValueError('scoped mapping declarations identify a ROM code range')
        bus(spec['when'])
        bus(spec['facts'])
    return value
