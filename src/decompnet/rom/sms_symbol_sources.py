"""Select declared sources; undeclared sidecars stay inspectable without physical-bank guesses."""
from dataclasses import dataclass
import hashlib
import zlib

from . import wla_bundle, wla_symbols
from .wla_layout import identity
from .export_sms_artifacts import read_regular


@dataclass
class Suggestions:
    sha256: str | None
    report: dict
    names: dict
    seeds: dict


def source_bytes(path):
    raw, info = read_regular(path, wla_symbols.MAX_BYTES + 1)
    if info.st_size > wla_symbols.MAX_BYTES:
        raise ValueError('symbol source exceeds the 8 MiB budget')
    return raw


def unqualified(raw, image):
    source = {'sha256': hashlib.sha256(raw).hexdigest(), 'size': len(raw)}
    report = {'version': 1, 'input': identity(image), 'layout': None, 'source': source,
              'records': [], 'aliases': [], 'ignored_lines': 0, 'state': 'rejected',
              'scope': 'unqualified source suggestions; no geometry or semantic approval established'}
    try:
        doc = wla_symbols.read(raw)
        source.update(symbol_version=doc.version, rom_crc32=doc.rom_crc32)
        state = 'requires_layout'
        if doc.rom_crc32 is not None and doc.rom_crc32 != f'{zlib.crc32(image):08x}':
            state = 'input_mismatch'
        elif doc.version not in (None, 1, 2, 3):
            state = 'unsupported_symbol_version'
        report.update(state=state, ignored_lines=doc.ignored,
                      records=[{**row, 'status': state, 'role': 'unknown', 'rom_offset': None, 'coordinates': []}
                               for row in doc.records])
    except (ValueError, TypeError):
        pass  # Raw private bytes remain intact; malformed metadata cannot become effective labels.
    return Suggestions(source['sha256'], report, {}, {})


def adjacent(path, image):
    try:
        return unqualified(source_bytes(path), image)
    except FileNotFoundError:
        return None
    except (OSError, ValueError):
        return Suggestions(None, {'version': 1, 'input': identity(image), 'layout': None, 'source': {},
                                  'records': [], 'aliases': [], 'ignored_lines': 0, 'state': 'unavailable'}, {}, {})


def select(path, image, *, reference=None, declaration=None, mapper='sega', root=None):
    if reference is not None:
        if declaration is not None:
            raise ValueError('choose a project symbol source or a direct layout, not both')
        if isinstance(reference, dict) and reference.get('format') == 'disabled':
            return adjacent(path, image) if reference.get('state') == 'rejected' else None
        return wla_bundle.load(root if root is not None else path.parent, reference, image, mapper=mapper)
    if declaration is not None:
        return wla_bundle.prepare(source_bytes(path), declaration, image, mapper=mapper)
    return adjacent(path, image)
