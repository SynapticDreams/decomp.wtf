"""Existing correction history, bounded inspection and the single selection path for active hints."""
import time

from ..network import NetworkError
from . import correction_policy as policy, correction_views as views, sms_annotation_context as context

MAX_ROWS = 10000


def identifier(value):
    if type(value) is not int or not 0 < value < 2**63:
        raise NetworkError('correction ID must be a positive integer')
    return value


def values(net, proj, rows):
    if any(row['annotation'] is not None or row['evidence'] is not None for row in rows):
        try:
            return context.load(net, proj['slug'])
        except NetworkError:
            pass
    return None


def one(net, proj, cid):
    row = net.store.one('SELECT c.*,a.name AS agent FROM corrections c LEFT JOIN agents a ON a.id=c.agent_id '
                        'WHERE c.project_id=? AND c.id=?', proj['id'], identifier(cid))
    if row is None:
        raise NetworkError('no such correction')
    return row


def listing(net, slug, *, before_id=None, limit=500):
    with context.read(net):
        return _listing(net, slug, before_id=before_id, limit=limit)


def _listing(net, slug, *, before_id, limit):
    proj = net._project(slug)
    cfg = net.cfg(proj)
    if type(limit) is not int or not 1 <= limit <= 500:
        raise NetworkError('correction page size must be 1 to 500')
    if before_id is not None:
        identifier(before_id)
    cursor = ' AND c.id<?' if before_id is not None else ''
    args = (proj['id'], before_id, limit + 1) if before_id is not None else (proj['id'], limit + 1)
    rows = net.store.all('SELECT c.*,a.name AS agent FROM corrections c LEFT JOIN agents a ON a.id=c.agent_id '
                         f'WHERE c.project_id=?{cursor} ORDER BY c.id DESC LIMIT ?', *args)
    bound = values(net, proj, rows)
    return {'corrections': [views.describe(net, row, cfg, bound) for row in rows[:limit]],
            'next_before': rows[limit - 1]['id'] if len(rows) > limit else None,
            'symbol_file': net.symbol_file(slug), 'coverage': net.coverage_file(slug)}


def inspect(net, slug, cid):
    with context.read(net):
        proj = net._project(slug)
        row = one(net, proj, cid)
        bound = values(net, proj, [row])
        result = views.detail(net, row, net.cfg(proj), bound)
        try:
            result['inspection_context'] = context.guard(net, proj)
        except NetworkError:
            result.update(inspection_context=None, inspection_guard='unavailable')
        return result


def undo(net, slug, cid):
    proj, _cfg = policy.project(net, slug)
    cid = identifier(cid)
    with net.store.tx() as db:
        if not db.execute('UPDATE corrections SET undone_at=? WHERE id=? AND project_id=? AND undone_at IS NULL',
                          (time.time(), cid, proj['id'])).rowcount:
            raise NetworkError("no such correction, or it's undone already")
    net._progress_cache.pop(proj['id'], None)
    return listing(net, slug)


def active(net, proj):
    with context.read(net):
        return _active(net, proj)


def _active(net, proj):
    rows = net.store.all('SELECT * FROM corrections WHERE project_id=? AND undone_at IS NULL ORDER BY id LIMIT ?',
                         proj['id'], MAX_ROWS + 1)
    if len(rows) > MAX_ROWS:
        raise NetworkError('correction analysis exceeds its row budget; inspect and undo superseded facts')
    cfg, bound = net.cfg(proj), values(net, proj, rows)
    return [row for row in rows if views.describe(net, row, cfg, bound)['active']]
