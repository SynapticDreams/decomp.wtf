"""Private SMS/GG resplit history and guarded undo; listings contain no stored source."""
from __future__ import annotations

import json
import time
from pathlib import Path

from ..handwritten import z80_reason
from ..network import NetworkError
from ..rom.sms import MAX_FUNCTION
from . import banked_resplit_checks as checks, banked_resplit_state as state
from .banked_resplit_restore import restore


def capture(net, proj):
    cfg = net.cfg(proj)
    inputs = state.external(Path(proj["root"]), cfg["rom"]["file"])
    with net.store.lock:
        if net.store.conn.in_transaction:
            return state.capture(net.store.conn, proj["id"], inputs)
        with net.store.tx() as db:
            return state.capture(db, proj["id"], inputs)


def unchanged(net, proj, expected: str):
    current = capture(net, proj)
    if state.encode(current)[1] != expected:
        raise NetworkError("project work or symbol/coverage inputs changed during resplit; preview again")
    return current


def mark_sms(db, pid: int) -> None:
    """The ordinary SMS set-aside rules, inside the same transaction as resplitting."""
    for row in db.execute("SELECT * FROM functions WHERE project_id=? AND status='open'", (pid,)).fetchall():
        meta = json.loads(row["meta"] or "{}")
        if not meta.get("for_agents") and (reason := z80_reason(row["target"] or b"", row["vram"] or 0,
                                                              capped=row["size"] >= MAX_FUNCTION)):
            db.execute("UPDATE functions SET status='asm', meta=? WHERE id=?",
                       (json.dumps({**meta, "asm_code": reason}), row["id"]))


def record(db, pid: int, before, after, summary) -> int:
    payload, digest = state.encode(before)
    after_digest = state.encode(after)[1]
    return db.execute("INSERT INTO resplit_history(project_id,created_at,before_state,before_digest,after_digest,summary) "
                      "VALUES(?,?,?,?,?,?)", (pid, time.time(), payload, digest, after_digest,
                                             json.dumps(summary))).lastrowid


def list_history(net, slug: str, before_id: int | None = None) -> dict:
    proj = net._project(slug)
    if before_id is not None and (type(before_id) is not int or not 0 < before_id < 2**63):
        raise NetworkError("history cursor must be a positive integer")
    cursor = " AND id<?" if before_id is not None else ""
    args = (proj["id"], before_id) if before_id is not None else (proj["id"],)
    rows = net.store.all("SELECT id,created_at,summary,undone_at FROM resplit_history "
                         f"WHERE project_id=?{cursor} ORDER BY id DESC LIMIT 51", *args)
    latest = net.store.one("SELECT MAX(id) AS id FROM resplit_history WHERE project_id=? AND undone_at IS NULL", proj["id"])
    return {"history": [{"id": row["id"], "created_at": row["created_at"], "undone_at": row["undone_at"],
                         "summary": json.loads(row["summary"])} for row in rows[:50]], "truncated": len(rows) > 50,
            "next_before": rows[49]["id"] if len(rows) > 50 else None, "latest_active_id": latest["id"]}


def undo(net, slug: str, history_id: int) -> dict:
    proj, now = net._project(slug), time.time()
    cfg = net.cfg(proj)
    if cfg.get("arch") != "z80" or slug in net.links or net.fork_slug(slug):
        raise NetworkError("resplit undo is for local SMS/GG projects")
    if type(history_id) is not int or not 0 < history_id < 2**63:
        raise NetworkError("resplit history ID must be a positive integer")
    checks.quiet(net, slug)
    with net.store.tx() as db:
        checks.quiet(net, slug)
        row = db.execute("SELECT * FROM resplit_history WHERE project_id=? AND id=?", (proj["id"], history_id)).fetchone()
        latest = db.execute("SELECT MAX(id) FROM resplit_history WHERE project_id=? AND undone_at IS NULL",
                            (proj["id"],)).fetchone()[0]
        if row is None or row["undone_at"] is not None or latest != history_id:
            raise NetworkError("undo the latest active resplit first")
        current = capture(net, proj)
        if state.encode(current)[1] != row["after_digest"]:
            raise NetworkError("project work or inputs changed after resplit; undo would overwrite newer work")
        checks.verify_input("z80", Path(proj["root"]) / cfg["rom"]["file"], cfg)
        before = state.decode(row["before_state"], row["before_digest"])
        restore(db, proj["id"], before)
        db.execute("UPDATE resplit_history SET undone_at=? WHERE id=?", (now, history_id))
        net._event(db, proj["id"], None, "split", "restored the previous resplit snapshot")
    invalidate(net, proj["id"])
    return {"undone": history_id}


def invalidate(net, pid):
    for cache in (net._xrefs, net._ops, net._syms, net._roms, net._progress_cache):
        cache.pop(pid, None)
    with net.twins._lock:
        net.twins._prints.pop(pid, None)
