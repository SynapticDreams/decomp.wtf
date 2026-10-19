"""Operator review authority is an application event, never a caller's JSON claim."""
import hashlib
import json

FIELDS = ('id', 'project_id', 'kind', 'rom_offset', 'cpu', 'count', 'reason', 'agent_id',
          'created_at', 'annotation', 'evidence')


def digest(row):
    raw = json.dumps({key: row[key] for key in FIELDS}, sort_keys=True, separators=(',', ':'), ensure_ascii=False)
    return hashlib.sha256(raw.encode()).hexdigest()


def trusted(net, row):
    receipt = net.store.one("SELECT detail FROM events WHERE project_id=? AND agent_id IS NULL "
                            "AND kind='correction_review' AND detail LIKE ? ORDER BY id DESC LIMIT 1",
                            row['project_id'], f"{row['id']}:%")
    return receipt is not None and receipt['detail'] == f"{row['id']}:{digest(row)}"


def record(net, db, row):
    net._event(db, row['project_id'], None, 'correction_review', f"{row['id']}:{digest(row)}")
