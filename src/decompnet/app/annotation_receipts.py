"""One exact-row operator authority mechanism for corrections, notes and symbols."""
import hashlib
import json


def digest(row, fields):
    raw = json.dumps({key: row[key] for key in fields}, sort_keys=True, separators=(',', ':'), ensure_ascii=False)
    return hashlib.sha256(raw.encode()).hexdigest()


def trusted(net, row, fields, *, kind, key):
    receipt = net.store.one('SELECT detail FROM events WHERE project_id=? AND agent_id IS NULL '
                            'AND kind=? AND detail LIKE ? ORDER BY id DESC LIMIT 1',
                            row['project_id'], kind, key + ':%')
    return receipt is not None and receipt['detail'] == key + ':' + digest(row, fields)


def record(net, db, row, fields, *, kind, key):
    net._event(db, row['project_id'], None, kind, key + ':' + digest(row, fields))
