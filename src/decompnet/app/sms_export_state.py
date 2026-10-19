"""Bound export metadata and current-input readiness; historical checks never imply current semantic approval."""
import hashlib
import json
from pathlib import Path

from ..rom import sms_identity
from ..rom.export_sms_report import identity
from ..rom.physical_ranges import union, length
from ..rom.export_sms_artifacts import fingerprint as artifact_fingerprint, read_regular
from ..store_annotations import snapshot_row


def stamp(net, proj):
    def blob(value):
        if isinstance(value, bytes):
            return identity(value)
        raise TypeError('unsupported project metadata')
    with net.store.lock:
        def read(db):
            digest = hashlib.sha256()
            cfg = json.loads(db.execute('SELECT config FROM projects WHERE id=?', (proj['id'],)).fetchone()['config'])
            cfg.pop('export', None)
            digest.update(json.dumps(cfg, sort_keys=True, default=blob).encode())
            queries = {
                'functions': 'SELECT id,name,rom_offset,vram,size,status,matched_source,meta,unit,relocs,asm FROM functions WHERE project_id=? ORDER BY id',
                'symbols': 'SELECT * FROM symbols WHERE project_id=? ORDER BY name',
                'data': 'SELECT * FROM data_regions WHERE project_id=? ORDER BY rom_offset',
                'headers': 'SELECT * FROM context_versions WHERE project_id=? ORDER BY version',
                'notes': 'SELECT * FROM notes WHERE project_id=? OR function_id IN (SELECT id FROM functions WHERE project_id=?) ORDER BY id'}
            for label, sql in queries.items():
                digest.update(label.encode())
                for row in db.execute(sql, (proj['id'],) * sql.count('?')):
                    digest.update(json.dumps(snapshot_row(label, row), sort_keys=True, default=blob).encode())
            return digest.hexdigest()
        if net.store.conn.in_transaction:
            return read(net.store.conn)
        with net.store.tx() as db:
            return read(db)


def input_state(proj, cfg):
    try:
        rom = cfg['rom']
        if rom.get('identity') is None and not rom.get('sha1'):
            return {'status': 'unbound'}
        path = Path(proj['root']) / rom['file']
        try:
            raw, info = read_regular(path, int(rom['size']) + 513)
        except FileNotFoundError:
            return {'status': 'missing'}
        except (OSError, ValueError):
            return {'status': 'unavailable'}
        if info.st_size > int(rom['size']) + 512:
            return {'status': 'different'}
        data = sms_identity.strip_copier_header(raw)
        sms_identity.verify_normalized(data, rom.get('identity'), rom.get('sha1'))
        return {'status': 'verified', 'normalized': identity(data)}
    except FileNotFoundError:
        return {'status': 'missing'}
    except OSError:
        return {'status': 'unavailable'}
    except (ValueError, TypeError, KeyError):
        return {'status': 'different'}


def summary(verification, context, coherent, *, fallback=()):
    mapping = lambda value: value if isinstance(value, dict) else {}
    build = mapping(verification.get('build'))
    raw_rows = mapping(build.get('documented')).get('routines')
    rows = [row for row in raw_rows if isinstance(row, dict)] if isinstance(raw_rows, list) else []
    if not rows:
        rows = [{'name': name, 'omission': reason, 'inserted': False} for name, reason in fallback]
    valid = verification.get('receipt_valid') is True
    inserted = [row for row in rows if valid and row.get('inserted') is True]
    omitted = [row for row in rows if not valid or not row.get('inserted')]
    normalized = mapping(mapping(verification.get('input')).get('normalized'))
    size = normalized.get('size') if type(normalized.get('size')) is int else 0
    def fields(value, keys):
        return {key: item[:128] if isinstance(item, str) else item for key, item in mapping(value).items()
                if key in keys and (item is None or type(item) in (str, int, bool))}
    input_info = fields(verification.get('input'), ('verified', 'expected_sha1'))
    if normalized:
        input_info['normalized'] = fields(normalized, ('size', 'sha256'))
    image = fields(verification.get('image'), ('checked', 'equal', 'first_difference'))
    for key in ('original', 'built'):
        if mapping(verification.get('image')).get(key):
            image[key] = fields(mapping(verification.get('image'))[key], ('size', 'sha256'))
    stored = mapping(build.get('c_reference')).get('stored_matches')
    stored = stored if type(stored) is int and 0 <= stored <= 100000 else None
    return {'version': 1, 'passed': verification.get('passed') is True, 'receipt_valid': valid,
            'errors': [str(value)[:128] for value in verification.get('errors', [])[:16]],
            'input': input_info, 'image': image,
            'process': fields(build.get('process'), ('completed', 'stage', 'exit_code', 'failure')),
            'documented': {'expected': len(rows), 'inserted': len(inserted), 'omitted': len(omitted),
                           'inserted_bytes': length(union([(row.get('flat'), row.get('size')) for row in inserted], size)),
                           'required': mapping(build.get('documented')).get('required') is True,
                           'omissions': [{'name': str(row.get('name', ''))[:512], 'reason': str(row.get('omission', 'unverified'))[:512]}
                                         for row in omitted[:100]], 'omissions_truncated': len(omitted) > 100},
            'context_sha256': context if coherent else None, 'coherent': coherent,
            'export_tree_sha256': verification.get('export_tree_sha256'),
            'export_inputs_coherent': verification.get('export_inputs_coherent') is True,
            'export_outputs_coherent': verification.get('export_outputs_coherent') is True,
            'context_scope': 'stored project metadata/source and exported tree; tool environment and external C dependencies are not qualified',
            'c_reference': {'stored_matches': stored,
                            'verified_by_build': False, 'source_linked': False},
            'typed_data': {'status': 'unqualified'}, 'semantic_review': {'status': 'unqualified'},
            'runtime_parity': {'status': 'not_tested'}}


def present(net, proj, cfg):
    state = input_state(proj, cfg)
    saved = cfg.get('export')
    if not saved:
        return state, None
    saved = dict(saved)
    verification = saved.get('verification')
    if not isinstance(verification, dict) or verification.get('version') != 1:
        saved['current'] = False
        saved['verification_state'] = 'legacy_unqualified'
    else:
        metadata_matches = verification.get('context_sha256') == stamp(net, proj)
        input_matches = state.get('status') == 'verified' and state.get('normalized') == verification.get('input', {}).get('normalized')
        tree = verification.get('export_tree_sha256')
        saved['artifacts_match'] = isinstance(tree, str) and tree == artifact_fingerprint(Path(proj['root']) / 'source', outputs=True)
        saved['current_reasons'] = [reason for check, reason in (
            (metadata_matches, 'project_metadata_changed_or_unbound'), (input_matches, 'input_unverified_or_different'),
            (saved['artifacts_match'], 'export_tree_changed_or_unavailable'),
            (verification.get('export_inputs_coherent') is True, 'export_inputs_not_attested'),
            (verification.get('export_outputs_coherent') is True, 'export_results_not_attested')) if not check]
        saved['current'] = not saved['current_reasons']
        saved['verification_state'] = 'current_metadata' if saved['current'] else 'historical'
    saved['historical_identical'] = saved.get('identical')
    saved['identical'] = saved.get('identical') is True and saved['current']
    return state, saved
