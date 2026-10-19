"""SMS/GG proof dimensions use physical unions; status and labels alone establish no semantic approval."""
import json

from ..rom.physical_ranges import union, length, overlap, acceptance_timeline


def calculate(rows, regions, size, asm_track):
    groups = {key: [] for key in ('all', 'code', 'asm', 'documented', 'c', 'eligible', 'data')}
    timeline = []
    pending = unknown = unplaced = invalid_meta = unbacked_c = unbacked_asm = to_document = 0
    for row in rows:
        low, count = row['rom_offset'], row['size']
        placed = type(low) is int and type(count) is int and count > 0 and 0 <= low < low + count <= size
        if not placed:
            unplaced += 1
        span = (low, count)
        groups['all'].append(span)
        try:
            meta = json.loads(row['meta'] or '{}')
            if not isinstance(meta, dict):
                raise ValueError('invalid metadata')
            valid_meta = True
        except (ValueError, TypeError):
            meta, invalid_meta = {}, invalid_meta + 1
            valid_meta = False
        status = row['status']
        try:
            is_code = status != 'asm' or (valid_meta and asm_track({**row, 'meta': json.dumps(meta)}))
        except (ValueError, TypeError, KeyError, AttributeError):
            is_code = False
        if is_code:
            groups['code'].append(span)
            to_document += status == 'asm'
        if status == 'asm':
            groups['asm'].append(span)
        elif status == 'documented':
            if row['has_source'] and placed:
                groups['documented'].append(span)
            else:
                unbacked_asm += 1
        else:
            groups['eligible'].append(span)
        if status == 'matched':
            if row['has_source'] and placed:
                groups['c'].append(span)
                timeline.append((low, count, row.get('matched_at')))
            else:
                unbacked_c += 1
        if status == 'documented':
            validation = meta.get('resplit_validation')
            if meta.get('sample') is True or (isinstance(validation, dict) and validation.get('semantic_review') == 'pending'):
                pending += 1
            else:
                unknown += 1
    groups['data'] = [(row['rom_offset'], row['size']) for row in regions]
    spans = {key: union(value, size) for key, value in groups.items()}
    totals = {key: length(value) for key, value in spans.items()}
    covered = totals['code'] + totals['data'] - overlap(spans['code'], spans['data'])
    return {'totals': {'bytes': totals['all'], 'matched_bytes': totals['c'], 'asm_bytes': totals['asm'],
                       'documented_bytes': totals['documented']},
            'mapped': {'rom': size, 'code': totals['code'], 'data': totals['data'], 'covered': covered,
                       'overlap': overlap(spans['code'], spans['data']),
                       'to_document': to_document},
            'metrics': {'version': 1, 'rom_bytes': size, 'discovered_code_bytes': totals['code'],
                        'c_reference': {'bytes': totals['c'], 'eligible_bytes': totals['eligible'],
                                        'unbacked_records': unbacked_c, 'scope': 'stored byte references',
                                        'timeline': acceptance_timeline(timeline, size),
                                        'source_linked': False, 'verified_by_export': False},
                        'documented_assembly': {'bytes': totals['documented'], 'unbacked_records': unbacked_asm,
                                                'scope': 'stored mechanical acceptance'},
                        'classified_data': {'bytes': totals['data'], 'code_overlap_bytes': overlap(spans['code'], spans['data'])},
                        'typed_data': {'status': 'unqualified', 'bytes': None},
                        'semantic_review': {'approved': 0, 'pending': pending, 'unknown': unknown,
                                            'scope': 'no source/context-bound approval receipts'},
                        'runtime_parity': {'status': 'not_tested'}, 'unplaced_or_clipped_functions': unplaced,
                        'invalid_metadata': invalid_meta}}


def read(net, proj, cfg):
    with net.store.lock:
        def query(db):
            rows = [dict(row) for row in db.execute('SELECT status,rom_offset,size,meta,matched_at, '
                    "(matched_source IS NOT NULL AND trim(matched_source)!='' AND target IS NOT NULL AND length(target)=size) "
                    'AS has_source FROM functions WHERE project_id=?', (proj['id'],))]
            regions = [dict(row) for row in db.execute('SELECT rom_offset,size FROM data_regions WHERE project_id=?', (proj['id'],))]
            return calculate(rows, regions, int(cfg['rom'].get('size') or 0), net.asm_track)
        if net.store.conn.in_transaction:
            return query(net.store.conn)
        with net.store.tx() as db:
            return query(db)
