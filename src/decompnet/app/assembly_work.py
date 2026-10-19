"""Assembly check receipts and deferred work, bound to the actual judge inputs.

Deferral changes queue eligibility, never source acceptance or cartridge evidence.
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
import re
import time
from functools import lru_cache
from pathlib import Path

from ..network import NetworkError

LABELS = ("Byte equality", "Address names", "ROM mapping", "Code and data", "Hardware names", "Names and comments")


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=lambda x:
        hashlib.sha256(x).hexdigest() if isinstance(x, bytes) else dataclasses.asdict(x)).encode()).hexdigest()


@lru_cache(maxsize=3)
def revision(arch):
    from .. import rom

    folder = Path(rom.__file__).parent
    files = {"z80": ("sms_asm.py", "sms_asm_refs.py", "sms_mapping.py", "sms_effects.py", "z80.py", "sms_hw.py", "gb_asm.py"),
             "mos6502": ("nes_asm.py", "nes_hw.py", "mos6502.py", "gb_asm.py"), "sm83": ("gb_asm.py", "gb_hw.py", "sm83.py")}[arch]
    return digest([hashlib.sha256((folder / name).read_bytes()).hexdigest() for name in files])


class AssemblyWork:
    def __init__(self, net):
        self.net = net

    def context(self, proj, fn, routine=None):
        cfg = self.net.cfg(proj)
        return digest({"routine": routine or self.net._routine(proj, fn), "profile": cfg.get("sms_profile"),
                       "identity": cfg.get("rom", {}).get("identity"), "validator": revision(proj["arch"])})

    def view(self, proj, fn):
        work = json.loads(fn["meta"] or "{}").get("assembly_work") or {}
        if not work:
            return {"deferred": False, "validation": None}
        current = self.context(proj, fn)
        validation, deferred = work.get("validation"), work.get("deferred")
        return {"deferred": bool(fn["status"] == "asm" and deferred and deferred["context"] == current),
                "reason": deferred["reason"] if deferred else "",
                "evidence_changed": bool(deferred and deferred["context"] != current),
                "validation": {**validation, "current": validation["context"] == current} if validation else None}

    def eligible(self, proj, fn):
        return self.net.asm_track(fn) and not self.view(proj, fn)["deferred"]

    def map_view(self, proj, row):
        if not json.loads(row["meta"] or "{}").get("assembly_work"):
            return {}
        view = self.view(proj, self.net._function(row["name"], proj["slug"]))
        validation = view.get("validation") or {}
        return {"deferred": view["deferred"],
                "assembly_bytes": validation.get("byte_identical") if validation.get("current") else None}

    def receipt(self, proj, fn, routine, source, verdict):
        exact = bool(routine.code) and verdict.same == verdict.size == len(routine.code)
        raw = [str(p) for p in verdict.problems]
        problems = [p[:2000] for p in raw[:64]]
        checks = []
        # Judges can return early. Never present a later check as passed without having reached it.
        reached = verdict.ok or (exact and all(re.match(r"^[2-6]\. ", p) for p in raw))
        for number, label in enumerate(LABELS, 1):
            failures = [p for p in raw if p.startswith(f"{number}. ")]
            if number == 1 and not exact:
                failures = failures or raw or ["The assembled bytes differ from the target."]
            pending = number == 3 and failures and all("pending" in p or "unresolved" in p for p in failures)
            state = "pending" if pending else "failed" if failures else "passed" if verdict.ok or reached or (number == 1 and exact) else "not_checked"
            checks.append({"number": number, "label": label, "state": state, "problems": [p[:2000] for p in failures[:12]], "truncated": len(failures) > 12})
        return {"context": self.context(proj, fn, routine), "source": digest(source), "at": time.time(),
                "same": verdict.same, "assembled": verdict.size, "target": len(routine.code),
                "byte_identical": exact, "checks": checks, "problems": problems, "truncated": len(raw) > 64}

    def record(self, db, fn, receipt, accepted):
        # Read current metadata: another tool may have added notes or a review while assembling.
        meta = json.loads(db.execute("SELECT meta FROM functions WHERE id=?", (fn["id"],)).fetchone()["meta"] or "{}")
        work = {"validation": receipt}
        if not accepted and receipt["byte_identical"] and any(
                c["number"] == 3 and c["state"] == "pending" for c in receipt["checks"]):
            work["deferred"] = {"context": receipt["context"], "reason": "Byte-identical draft; ROM mapping evidence is unresolved.",
                                "at": time.time(), "origin": "validation"}
            db.execute("DELETE FROM claims WHERE function_id=?", (fn["id"],))
        meta["assembly_work"] = work
        db.execute("UPDATE functions SET meta=? WHERE id=?", (json.dumps(meta), fn["id"]))
        return bool(work.get("deferred"))

    def change(self, slug, function, *, reason=None, resume=False, agent=None):
        net, proj = self.net, self.net._project(slug)
        if net.fork_slug(slug) or slug in net.links:
            raise NetworkError("deferred documentation is managed on the local ROM project")
        fn = net._function(function, slug)
        if not net.asm_track(fn):
            raise NetworkError("only hand-written routines awaiting documentation can be deferred or resumed")
        if not resume and (not isinstance(reason, str) or not 10 <= len(reason.strip()) <= 1000):
            raise NetworkError("give a reason of 10 to 1000 characters explaining what must change")
        context = self.context(proj, fn)
        with net.store.tx() as db:
            net._expire_claims(db)
            held = db.execute("SELECT agent_id FROM claims WHERE function_id=?", (fn["id"],)).fetchone()
            if agent is not None and held is None:
                raise NetworkError("claim the assembly routine before deferring it")
            own = agent is not None and held and held["agent_id"] == agent.id
            manual = agent is None and held and net._agent_name(held["agent_id"]) == "you"
            if held and not (own or manual):
                raise NetworkError("this routine is being worked on; wait for its helper to release it")
            row = db.execute("SELECT status,meta FROM functions WHERE id=?", (fn["id"],)).fetchone()
            if row is None or row["status"] != "asm":
                raise NetworkError("the routine changed; refresh before changing its queue state")
            meta = json.loads(row["meta"] or "{}")
            work = meta.setdefault("assembly_work", {})
            if resume:
                work.pop("deferred", None)
            else:
                work["deferred"] = {"reason": reason.strip(), "context": context, "at": time.time(), "origin": "manual"}
                db.execute("DELETE FROM claims WHERE function_id=?", (fn["id"],))
            db.execute("UPDATE functions SET meta=? WHERE id=?", (json.dumps(meta), fn["id"]))
            net._event(db, proj["id"], agent.id if agent else None, "assembly_queue",
                       f"{fn['name']}: documentation {'resumed' if resume else 'deferred'}")
        return {"name": fn["name"], "deferred": not resume}
