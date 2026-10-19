"""Non-destructive symbol writes. Metadata follows only the same original subject, never a replacement."""
from . import annotation_archives
from ..network import NetworkError

FIELDS = ('address', 'size', 'kind')


def get(db, pid, name):
    return db.execute('SELECT * FROM symbols WHERE project_id=? AND name=?', (pid, name)).fetchone()


def save(db, pid, name, address, size, kind, preview=None, *, reason='symbol replacement'):
    if not db.in_transaction:
        raise NetworkError('symbol writes require a transaction')
    old = get(db, pid, name)
    changed = old is not None and tuple(old[key] for key in FIELDS) != (address, size, kind)
    if changed:
        annotation_archives.save(db, 'symbol', old, reason)
    db.execute('INSERT INTO symbols(project_id,name,address,size,kind,preview) VALUES(?,?,?,?,?,?) '
               'ON CONFLICT(project_id,name) DO UPDATE SET address=excluded.address,size=excluded.size,kind=excluded.kind,'
               'preview=excluded.preview,annotation=CASE WHEN ? THEN NULL ELSE symbols.annotation END,'
               'evidence=CASE WHEN ? THEN NULL ELSE symbols.evidence END,subject=CASE WHEN ? THEN NULL ELSE symbols.subject END',
               (pid, name, address, size, kind, preview, changed, changed, changed))


def update(db, pid, name, **changes):
    old = get(db, pid, name)
    if old is None:
        return
    if not set(changes) <= {*FIELDS, 'preview'}:
        raise ValueError('unsupported symbol record fields')
    values = {key: changes.get(key, old[key]) for key in (*FIELDS, 'preview')}
    save(db, pid, name, **values, reason='symbol subject changed')


def remove(db, pid, name, *, reason='symbol removed'):
    if not db.in_transaction:
        raise NetworkError('symbol writes require a transaction')
    annotation_archives.save(db, 'symbol', get(db, pid, name), reason)
    return db.execute('DELETE FROM symbols WHERE project_id=? AND name=?', (pid, name)).rowcount


def rename(db, pid, old, new):
    row = get(db, pid, old)
    if row is None or old == new:
        return int(row is not None)
    remove(db, pid, old, reason='symbol renamed')
    save(db, pid, new, *(row[key] for key in FIELDS), preview=row['preview'], reason='rename replaced another symbol')
    return 1
