"""Bounded WLA symbol records and conservative layout normalization, preserving aliases and source identity.

Format reference: https://github.com/vhelin/wla-dx/blob/v10.7/doc/symbols.rst
Labels name both code and data; only declared code views or automatic code markers become seed suggestions.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
import hashlib
import io
import re
import zlib

from .wla_layout import Layout, identity

MAX_BYTES = 8 * 1024 * 1024
MAX_RECORDS = 100_000
MAX_LINES = 250_000
MAX_VIEW_CHECKS = 1_000_000
MAX_COORDINATES = 200_000
LABEL = re.compile(r'^([0-9a-fA-F]{1,4}):([0-9a-fA-F]{4})\s+([A-Za-z_.@$][A-Za-z0-9_.@$]{0,127})$')
AUTO_CODE = re.compile(r'^_LABEL_[0-9a-fA-F]+_?$')
NAME = re.compile(r'^[A-Za-z][A-Za-z0-9_]*$')


@dataclass
class Document:
    raw: bytes
    sha256: str
    version: int | None
    rom_crc32: str | None
    records: list[dict]
    ignored: int


@dataclass
class Normalized:
    document: Document
    input: dict
    layout: dict
    records: list[dict]
    names: dict
    seeds: dict
    aliases: dict

    def report(self):
        """Inspectable records, never raw comments/source paths or claims of semantic approval."""
        return {'version': 1, 'input': self.input, 'layout': self.layout,
                'source': {'sha256': self.document.sha256, 'size': len(self.document.raw),
                           'symbol_version': self.document.version, 'rom_crc32': self.document.rom_crc32},
                'records': self.records, 'ignored_lines': self.document.ignored,
                'aliases': [{'physical_bank': bank, 'cpu': cpu, 'names': names}
                            for (bank, cpu), names in self.aliases.items()],
                'scope': 'declared source coordinates and seed suggestions; semantic approval not established'}


def read(raw: bytes) -> Document:
    if not isinstance(raw, bytes) or len(raw) > MAX_BYTES:
        raise ValueError('WLA symbol source must be bytes within the 8 MiB budget')
    text = raw.decode('utf-8-sig')
    section, version, checksum, ignored, records = 'labels', None, None, 0, []
    for number, original in enumerate(io.StringIO(text, newline=None), 1):
        if number > MAX_LINES:
            raise ValueError('WLA symbol source exceeds its line budget')
        line = original.split(';', 1)[0].strip()
        if not line:
            continue
        if line.startswith('[') and line.endswith(']'):
            section = line[1:-1].strip().lower()
            continue
        if section == 'information' and line.startswith('version'):
            if not re.fullmatch(r'version [0-9]{1,6}', line) or version is not None:
                raise ValueError('invalid or duplicate WLA symbol version')
            version = int(line.split()[1])
        elif section == 'rom checksum':
            if not re.fullmatch(r'[0-9a-fA-F]{8}', line) or checksum is not None:
                raise ValueError('invalid or duplicate WLA ROM checksum')
            checksum = line.lower()
        elif section == 'labels' and (match := LABEL.fullmatch(line)):
            records.append({'line': number, 'bank': int(match[1], 16), 'cpu': int(match[2], 16), 'name': match[3]})
            if len(records) > MAX_RECORDS:
                raise ValueError('WLA symbol source exceeds the 100,000-record budget')
        else:
            ignored += 1
    return Document(raw, hashlib.sha256(raw).hexdigest(), version, checksum, records, ignored)


def normalize(document: Document, layout: Layout, image: bytes) -> Normalized:
    if layout.declaration['input'] != identity(image):
        raise ValueError('validated WLA layout refers to a different normalized input')
    if document.rom_crc32 is not None and document.rom_crc32 != f'{zlib.crc32(image):08x}':
        raise ValueError('WLA ROM checksum differs from normalized input')
    records, checks, coordinates = [], 0, 0
    for original in document.records:
        checks += len(layout.views.get(original['bank'], ()))
        if checks > MAX_VIEW_CHECKS:
            raise ValueError('WLA normalization exceeds its view-check budget')
        row = {**original, 'coordinates': layout.coordinates(original['bank'], original['cpu']),
               'status': 'suggestion', 'role': 'unknown', 'rom_offset': None}
        coordinates += len(row['coordinates'])
        if coordinates > MAX_COORDINATES:
            raise ValueError('WLA normalization exceeds its coordinate budget')
        coords = {(c['space'], c['rom_offset'], c['role']) for c in row['coordinates']}
        if document.version not in (None, 1, 2, 3):
            row['status'] = 'unsupported_symbol_version'
        elif len(coords) > 1:
            row['status'] = 'ambiguous_view'
        elif not coords:
            row['status'] = 'unmapped'
        else:
            space, flat, role = next(iter(coords))
            name = row['name']
            row.update(role=role, rom_offset=flat)
            if space != 'rom':
                row['status'] = space
            elif name.startswith(('_DATA_', '_RAM_')):
                row.update(status='data' if name.startswith('_DATA_') else 'ram', role='data')
            elif role == 'data':
                row['status'] = 'data'
            elif not NAME.fullmatch(name) and not AUTO_CODE.fullmatch(name):
                row['status'] = 'local'
            elif role == 'code' or AUTO_CODE.fullmatch(name):
                row.update(status='code', role='code')
        records.append(row)
    by_name, by_location, by_flat = defaultdict(list), defaultdict(list), defaultdict(list)
    for row in records:
        by_name[row['name']].append(row)
        if row['rom_offset'] is not None:
            by_location[(row['rom_offset'], row['cpu'])].append(row)
            if row['status'] == 'code':
                by_flat[row['rom_offset']].append(row)
    for rows in by_name.values():
        positions = {(r['rom_offset'], r['cpu'], tuple((c['space'], c['rom_offset']) for c in r['coordinates'])) for r in rows}
        if len(positions) > 1:
            for row in rows:
                row['status'] = 'conflicting_name'
    for rows in by_location.values():
        if {'code', 'data'} <= {row['role'] for row in rows}:
            for row in rows:
                row['status'] = 'conflicting_role'
    for rows in by_flat.values():
        if len({row['cpu'] for row in rows}) > 1:
            for row in rows:
                row['status'] = 'ambiguous_cpu_entry'
    aliases, seen_aliases = defaultdict(list), defaultdict(set)
    seeds = {}
    for row in records:
        if row['status'] != 'code':
            continue
        key = (row['rom_offset'] // 0x4000, row['cpu'])
        seeds.setdefault(key, row['name'])
        if NAME.fullmatch(row['name']) and row['name'] not in seen_aliases[key]:
            aliases[key].append(row['name'])
            seen_aliases[key].add(row['name'])
    names = {key: values[0] for key, values in aliases.items()}
    return Normalized(document, identity(image), layout.declaration, records, names, seeds, dict(aliases))
