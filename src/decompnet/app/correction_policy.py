"""Shared correction bounds and protection of accepted source; no address guessing."""
import time

from ..network import NetworkError

KINDS = {'data': ("isn't code", 'bytes'), 'code': ('is where a function starts', ''),
         'table': ('is a table of handler addresses', 'entries'),
         'operands': ('is a routine that reads bytes after its call', 'bytes after each call'),
         'noreturn': ('is a routine that never returns', '')}


def project(net, slug, *, sms=False):
    proj = net._project(slug)
    cfg = net.cfg(proj)
    if net._link(slug) is not None or cfg.get('link'):
        raise NetworkError("in a room, leave a note (add_note): the room's host splits the game")
    if str(cfg.get('arch') or '').lower() not in ('sm83', 'z80') or net.fork_slug(proj['slug']):
        raise NetworkError('corrections are for Game Boy and Master System projects')
    if sms and (cfg.get('platform') not in ('sms', 'gg') or cfg.get('kind') != 'rom'):
        raise NetworkError('structured corrections require a local SMS/GG ROM project')
    return proj, cfg


def reason(value):
    if not isinstance(value, str):
        raise NetworkError('say how you know, in a sentence')
    value = ' '.join(value.split())
    if not 20 <= len(value) <= 1000:
        raise NetworkError('say how you know, in a sentence of 20 to 1000 characters')
    return value


def validate_count(kind, value):
    low, high = {'data': (1, 0x4000), 'table': (1, 128), 'operands': (1, 8)}.get(kind, (0, 0))
    if type(value) is not int or not low <= value <= high:
        raise NetworkError(f'count must be an integer from {low} to {high}')
    return value


def extent(kind, count):
    return count if kind == 'data' else count * 2 if kind == 'table' else 1


def bounds(kind, offset, count, rom_size):
    if kind not in KINDS or type(offset) is not int:
        raise NetworkError('unsupported correction kind or offset')
    count = validate_count(kind, count)
    size = extent(kind, count)
    if offset < 0 or offset + size > rom_size:
        raise NetworkError('correction extends past the end of the ROM')
    if kind == 'data' and offset // 0x4000 != (offset + size - 1) // 0x4000:
        raise NetworkError("data stays in its bank: mark each bank's part on its own")
    return size


def conflict(net, pid, kind, offset, size):
    if kind in ('number', 'mapping'):
        return None  # Neither kind classifies these bytes as data or updates the live bus.
    for row in net.store.all("SELECT name,status,rom_offset FROM functions WHERE project_id=? "
                             "AND status IN ('matched','documented') AND rom_offset<? AND rom_offset+size>?",
                             pid, offset + size, offset):
        if kind == 'code' and row['rom_offset'] == offset:
            continue
        return f"{row['name']} is {row['status']} there: its bytes are code"
    return None


def rate(net, agent, now=None):
    n = net.store.one("SELECT COUNT(*) AS n FROM events WHERE agent_id=? AND kind='correction' AND created_at>?",
                      agent.id, (time.time() if now is None else now) - 3600)['n']
    if n >= net.CORRECTIONS_PER_HOUR:
        raise NetworkError(f'you made {n} corrections in the last hour: leave a note (add_note) for the rest')
