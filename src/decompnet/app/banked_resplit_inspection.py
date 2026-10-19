"""Stateless, bounded inspection of a specific SMS/GG preview; never source bodies or writes."""
from ..network import NetworkError
from . import banked_resplit_changes as changes, sms_resplit_revalidate as revalidate

PAGE = 100


def parse(value, *, arch, apply, expected_plan):
    if value is None:
        return None
    if arch != 'z80' or apply:
        raise NetworkError('preview inspection is read-only and supported only for SMS/GG')
    if expected_plan is None:
        raise NetworkError('preview before requesting inspection pages')
    if not isinstance(value, dict) or value.get('kind') not in ('changed', 'checks', 'overlaps'):
        raise NetworkError('inspection kind must be changed, checks or overlaps')
    fields = {'kind', 'offset', 'function'} if value['kind'] == 'overlaps' else {'kind', 'offset'}
    if set(value) != fields or type(value['offset']) is not int or not 0 <= value['offset'] < 2**63:
        raise NetworkError('inspection needs an integer offset and only its declared fields')
    if 'function' in fields and (type(value['function']) is not int or not 0 < value['function'] < 2**63):
        raise NetworkError('inspection function must be a positive integer ID')
    return dict(value)


def inspect(selection, before, candidates, kept, source_state, regions, *, force=False):
    kind, offset = selection['kind'], selection['offset']
    old = before['tables']['functions']
    extra = {}
    if kind == 'overlaps':
        row = next((row for row in old if row['id'] == selection['function']), None)
        if row is None:
            raise NetworkError('inspection function is unavailable in this project preview')
        rows = changes.overlapping(row, candidates)
        extra['function'] = changes.identity(row)
        encode = changes.coordinate
    elif kind == 'checks':
        rows = revalidate.affected(source_state, candidates, regions, force=force)
        proposed = {fn.rom: fn for fn in candidates}
        def encode(row):
            candidate = proposed.get(row['rom_offset'])
            return {**changes.identity(row), 'retained': row['id'] in kept,
                    'proposed': changes.coordinate(candidate) if candidate else None}
    else:
        rows = [row for row in old if row['id'] not in kept]
        encode = lambda row: changes.detail(row, candidates)
    if offset > len(rows):
        raise NetworkError('inspection offset is outside the preview records')
    end = offset + PAGE
    return {'kind': kind, 'offset': offset, 'total': len(rows), 'limit': PAGE,
            'next_offset': end if end < len(rows) else None, 'rows': [encode(row) for row in rows[offset:end]], **extra}
