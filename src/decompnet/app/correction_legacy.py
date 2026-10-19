"""The existing five correction kinds, with strict extents and transactional source protection."""
import time

from ..network import NetworkError
from . import correction_policy as policy


def add(net, agent, project, kind, at, reason, count=0, function=''):
    proj, cfg = policy.project(net, project)
    kind = str(kind or '').strip().lower()
    if kind not in policy.KINDS:
        raise NetworkError(f"kind is one of {', '.join(policy.KINDS)}")
    reason = policy.reason(reason)
    count = policy.validate_count(kind, count)
    flat, cpu = net._banked_at(proj, at, function or None)
    size = policy.bounds(kind, flat, count, cfg['rom']['size'])
    where = f'{flat // 0x4000:02X}:{cpu:04X}'
    what = f'{where} {policy.KINDS[kind][0]}' + (f' ({count} {policy.KINDS[kind][1]})' if count else '')
    now = time.time()
    with net.store.tx() as db:
        current, current_cfg = policy.project(net, proj['slug'])
        if current['config'] != proj['config']:
            raise NetworkError('project settings changed; retry the correction')
        policy.bounds(kind, flat, count, current_cfg['rom']['size'])
        if problem := policy.conflict(net, proj['id'], kind, flat, size):
            raise NetworkError(problem)
        policy.rate(net, agent, now)
        owner = db.execute('SELECT id FROM functions WHERE project_id=? AND rom_offset<=? AND rom_offset+size>?',
                           (proj['id'], flat, flat)).fetchone()
        db.execute('INSERT INTO corrections(project_id,kind,rom_offset,cpu,count,reason,agent_id,created_at) VALUES(?,?,?,?,?,?,?,?)',
                   (proj['id'], kind, flat, cpu, count, reason, agent.id, now))
        db.execute('INSERT INTO notes(project_id,function_id,agent_id,text,created_at) VALUES(?,?,?,?,?)',
                   (proj['id'], owner['id'] if owner else None, agent.id, f'correction: {what}: {reason}', now))
        net._event(db, proj['id'], agent.id, 'correction', what)
    return (f"✅ noted: {what}. It's used when the game is split again (a person does that from Settings, and can "
            'undo it). Until then, work on as it is, or release the function with a note.')
