"""Declared assembler bank/slot geometry; it never establishes a live cartridge mapping.

WLA 10.7 .ROMBANKMAP and .MEMORYMAP describe different coordinate systems:
https://github.com/vhelin/wla-dx/blob/v10.7/doc/asmdiv.rst
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib

from .sms_mapping import BANK, Mapper, rom_coordinate

MAX_BANKS = 4096
MAX_VIEWS = 8192


def identity(image: bytes) -> dict:
    return {'size': len(image), 'sha256': hashlib.sha256(image).hexdigest()}


def integer(value, low, high):
    if type(value) is not int or not low <= value <= high:
        raise ValueError('WLA layout integer is outside its allowed range')
    return value


def fields(value, required):
    if not isinstance(value, dict) or set(value) != set(required):
        raise ValueError('unsupported WLA layout fields')


def entries(value, limit):
    if not isinstance(value, list) or not 1 <= len(value) <= limit:
        raise ValueError('WLA layout list is empty or exceeds its budget')
    return value


@dataclass
class Layout:
    declaration: dict
    model: Mapper
    banks: dict
    slots: dict
    views: dict

    def coordinates(self, bank, cpu):
        """All matching declared views, including conflicts, RAM and impossible hardware coordinates."""
        out = []
        for view in self.views.get(bank, ()):
            slot = self.slots[view['slot']]
            offset = cpu - slot['start']
            if not view['offset'] <= offset < view['offset'] + view['size']:
                continue
            row = {'slot': slot['id'], 'space': slot['space'], 'role': view['role'], 'rom_offset': None,
                   'physical_bank': None, 'cpu': cpu}
            if slot['space'] == 'rom':
                flat = self.banks[bank]['offset'] + offset
                row.update(rom_offset=flat, physical_bank=flat // BANK)
                if rom_coordinate(self.model, flat // BANK, cpu).rom_offset != flat:
                    row.update(space='unresolved', reason='declared assembler coordinate contradicts cartridge geometry')
            out.append(row)
        return out


def declare(value, image: bytes, *, mapper='sega') -> Layout:
    """Validate a versioned, revision-bound declaration without interpreting arbitrary assembly source."""
    fields(value, ('version', 'input', 'banks', 'slots', 'views'))
    if type(value['version']) is not int or value['version'] != 1:
        raise ValueError('unsupported WLA layout version')
    fields(value['input'], ('size', 'sha256'))
    if type(value['input']['size']) is not int or value['input'] != identity(image):
        raise ValueError('WLA layout refers to a different normalized input')
    model = Mapper(mapper, len(image))
    banks, slots, views, all_views = {}, {}, {}, []
    end = 0
    for row in entries(value['banks'], MAX_BANKS):
        fields(row, ('id', 'offset', 'size'))
        bank = integer(row['id'], 0, 65535)
        offset = integer(row['offset'], 0, len(image) - 1)
        size = integer(row['size'], 1, 65536)
        if bank in banks or offset != end or offset + size > len(image):
            raise ValueError('WLA banks must cover the input once in physical order')
        banks[bank] = dict(row)
        end += size
    if end != len(image):
        raise ValueError('WLA banks do not cover the normalized input')
    for row in entries(value['slots'], 256):
        fields(row, ('id', 'start', 'size', 'space'))
        slot = integer(row['id'], 0, 255)
        start = integer(row['start'], 0, 65535)
        size = integer(row['size'], 1, 65536)
        if slot in slots or start + size > 65536 or row['space'] not in ('rom', 'ram', 'unknown'):
            raise ValueError('invalid or duplicate WLA slot')
        slots[slot] = dict(row)
    for row in entries(value['views'], MAX_VIEWS):
        fields(row, ('bank', 'slot', 'offset', 'size', 'role'))
        bank = integer(row['bank'], 0, 65535)
        slot = integer(row['slot'], 0, 255)
        offset = integer(row['offset'], 0, 65535)
        size = integer(row['size'], 1, 65536)
        if slot not in slots or row['role'] not in ('code', 'data', 'unknown'):
            raise ValueError('invalid WLA view slot or role')
        if offset + size > slots[slot]['size'] or (slots[slot]['space'] == 'rom' and
                (bank not in banks or offset + size > banks[bank]['size'])):
            raise ValueError('WLA view extends outside its bank or slot')
        copied_row = dict(row)
        views.setdefault(bank, []).append(copied_row)
        all_views.append(copied_row)
    # Retain an independent copy: mutating caller-owned dictionaries must not change validated geometry.
    copied = {'version': 1, 'input': dict(value['input']), 'banks': list(banks.values()),
              'slots': list(slots.values()), 'views': all_views}
    return Layout(copied, model, banks, slots, views)
