"""Bounded note/symbol research inspection on existing rows, including original archived subjects."""
from ..network import NetworkError
from . import annotation_keys as keys, annotation_views as views, sms_annotation_context as context


def values(net, proj, rows):
    if any(any(row[key] is not None for key in ('annotation', 'evidence', 'subject')) for row in rows):
        try:
            return context.load(net, proj['slug'])
        except NetworkError:
            pass
    return None


def inspect(net, slug, kind, key):
    with context.read(net):
        proj = net._project(slug)
        row = keys.fetch(net, proj, kind, key)
        result = views.describe(net, kind, row, net.cfg(proj), values(net, proj, [row]), full=True)
        try:
            result['inspection_context'] = context.guard(net, proj)
        except NetworkError:
            result.update(inspection_context=None, inspection_guard='unavailable')
        return result


def listing(net, slug, kind, *, before_id=None, after_symbol=None, limit=50):
    if kind not in keys.TABLES or type(limit) is not int or not 1 <= limit <= 100:
        raise NetworkError('research pages require note/symbol kind and a size from 1 to 100')
    if before_id is not None:
        keys.key('note', before_id)
    if after_symbol is not None:
        keys.key('symbol', after_symbol)
    with context.read(net):
        proj = net._project(slug)
        cursor = ' AND id<?' if kind == 'note' and before_id is not None else \
            ' AND name>?' if kind == 'symbol' and after_symbol is not None else ''
        args = [proj['id']]
        if cursor:
            args.append(before_id if kind == 'note' else after_symbol)
        order = 'id DESC' if kind == 'note' else 'name'
        rows = net.store.all(f'SELECT * FROM {keys.TABLES[kind]} WHERE project_id=?{cursor} ORDER BY {order} LIMIT ?',
                             *args, limit + 1)
        bound = values(net, proj, rows)
        next_key = (rows[limit - 1]['id'] if kind == 'note' else rows[limit - 1]['name']) if len(rows) > limit else None
        return {'kind': kind, 'records': [views.describe(net, kind, row, net.cfg(proj), bound) for row in rows[:limit]],
                'next_before': next_key if kind == 'note' else None, 'next_symbol': next_key if kind == 'symbol' else None}
