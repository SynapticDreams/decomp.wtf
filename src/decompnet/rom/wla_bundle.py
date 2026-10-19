"""Immutable private symbol-source bundles; project metadata selects an exact content hash."""
from __future__ import annotations

import base64
from dataclasses import dataclass
import hashlib
import json
import os
import re
import zlib

from . import wla_layout, wla_symbols
from .export_sms_artifacts import read_regular

MAX_BUNDLE = 16 * 1024 * 1024


@dataclass
class Prepared:
    sha256: str
    payload: bytes
    report: dict
    names: dict
    seeds: dict


def prepare(raw, declaration, image, *, mapper='sega'):
    document = wla_symbols.read(raw)
    if document.rom_crc32 is not None and document.rom_crc32 != f'{zlib.crc32(image):08x}':
        raise ValueError('WLA ROM checksum differs from normalized input')
    if declaration is None:
        report = {'version': 1, 'input': wla_layout.identity(image), 'layout': None,
                  'source': {'sha256': document.sha256, 'size': len(raw), 'symbol_version': document.version,
                             'rom_crc32': document.rom_crc32},
                  'records': [{**row, 'status': 'requires_layout', 'coordinates': [], 'rom_offset': None,
                               'role': 'unknown'} for row in document.records],
                  'ignored_lines': document.ignored, 'aliases': [], 'state': 'requires_layout'}
        names, seeds = {}, {}
    else:
        layout = wla_layout.declare(declaration, image, mapper=mapper)
        imported = wla_symbols.normalize(document, layout, image)
        report = imported.report() | {'state': 'declared' if document.version in (None, 1, 2, 3) else 'unsupported_symbol_version'}
        declaration, names, seeds = imported.layout, imported.names, imported.seeds
    if not document.records:
        raise ValueError('no WLA bank:address label records in that source')
    payload = json.dumps({'version': 1, 'input': wla_layout.identity(image),
                          'source': base64.b64encode(raw).decode('ascii'), 'layout': declaration},
                         sort_keys=True, separators=(',', ':')).encode()
    if len(payload) > MAX_BUNDLE:
        raise ValueError('WLA source bundle exceeds the 16 MiB budget')
    return Prepared(hashlib.sha256(payload).hexdigest(), payload, report, names, seeds)


def path(root, reference):
    if not isinstance(reference, dict) or reference.get('format') != 'wla-bundle' or \
            type(reference.get('version')) is not int or reference['version'] != 1 or \
            not isinstance(reference.get('bundle_sha256'), str) or not re.fullmatch('[0-9a-f]{64}', reference['bundle_sha256']):
        raise ValueError('unsupported WLA source reference')
    directory = root / '.symbol-imports'
    if directory.is_symlink():
        raise ValueError('WLA source directory must not be a symlink')
    return directory / (reference['bundle_sha256'] + '.json')


def verified(root, reference):
    raw, info = read_regular(path(root, reference), MAX_BUNDLE + 1)
    if info.st_size > MAX_BUNDLE or hashlib.sha256(raw).hexdigest() != reference['bundle_sha256']:
        raise ValueError('WLA source bundle is changed or exceeds its budget')
    return raw


def publish(root, prepared):
    reference = {'format': 'wla-bundle', 'version': 1, 'bundle_sha256': prepared.sha256}
    target = path(root, reference)
    target.parent.mkdir(mode=0o700, exist_ok=True)
    try:
        descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    except FileExistsError:
        verified(root, reference)
    else:
        try:
            with os.fdopen(descriptor, 'wb') as stream:
                stream.write(prepared.payload)
        except BaseException:
            target.unlink(missing_ok=True)
            raise
    return reference


def load(root, reference, image, *, mapper='sega'):
    value = json.loads(verified(root, reference))
    wla_layout.fields(value, ('version', 'input', 'source', 'layout'))
    if type(value['version']) is not int or value['version'] != 1 or value['input'] != wla_layout.identity(image):
        raise ValueError('WLA source bundle refers to a different normalized input or version')
    if not isinstance(value['source'], str) or len(value['source']) > 4 * ((wla_symbols.MAX_BYTES + 2) // 3):
        raise ValueError('WLA source encoding exceeds its budget')
    raw = base64.b64decode(value['source'], validate=True)
    result = prepare(raw, value['layout'], image, mapper=mapper)
    if result.sha256 != reference['bundle_sha256'] or (reference.get('source_sha256') is not None and
            result.report['source']['sha256'] != reference['source_sha256']):
        raise ValueError('WLA source bundle metadata differs')
    return result
