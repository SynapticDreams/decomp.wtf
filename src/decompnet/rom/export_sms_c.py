"""Stored C-byte references retain current unit context without claiming compilation or linked replacement."""
import hashlib
import json

from ..project import compiler_settings
from .export_sms_report import source_digest


def write(net, proj, out, rows):
    if not rows:
        return []
    cfg, records = net.cfg(proj), []
    for row in rows:
        unit = row['unit'] or ''
        context = net._context(proj['id'], unit)
        separate = bool(context['unit'] or unit in cfg['compiler'].get('units', {}))
        folder = 'c/unit_' + hashlib.sha256(unit.encode()).hexdigest()[:16] if separate else 'c'
        directory = out / folder
        directory.mkdir(parents=True, exist_ok=True)
        header = context['header'] or ''
        (directory / 'context.h').write_text(header, encoding='utf-8', newline='')
        filename = f'{folder}/{row["name"]}.c'
        (out / filename).write_text(
            '/* Stored C-byte reference. This export does not compile or link this file.\n'
            '   The header and compiler settings describe context at export, not attested prior acceptance. */\n'
            '#include "context.h"\n\n' + row['matched_source'].strip() + '\n', encoding='utf-8', newline='')
        records.append({'name': row['name'], 'file': filename, 'unit': unit, 'context_unit': context['unit'],
                        'context_version': context['version'], 'context_sha256': hashlib.sha256(header.encode()).hexdigest(),
                        'source_sha256': source_digest(row['matched_source']), 'rom_offset': row['rom_offset'], 'size': row['size'],
                        'target_sha256': hashlib.sha256(row['target'] or b'').hexdigest(),
                        'compiler_context_at_export': compiler_settings(cfg, unit), 'verified_by_export': False,
                        'source_linked': False, 'acceptance_context': 'not_attested'})
    (out / 'c' / 'references.json').write_text(json.dumps({'version': 1, 'scope': 'stored byte references',
        'runtime_parity': 'not_tested', 'references': records}, indent=2) + '\n', encoding='utf-8')
    return records
