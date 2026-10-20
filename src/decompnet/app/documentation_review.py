"""Independent AI assessments of accepted assembly; never human approval or source edits."""
from __future__ import annotations

import json
import time

from ..network import NetworkError
from .assembly_work import digest


READ_TOOLS = {"get_documentation_review", "get_function", "read_data", "guide", "submit_documentation_review"}
VERDICTS = {"supported", "needs_changes", "uncertain"}


class DocumentationReview:
    def __init__(self, net):
        self.net = net
        self.active = {}

    def target(self, slug, function):
        net = self.net
        proj, fn = net._project(slug), net._function(function, slug)
        if net.fork_slug(slug) or slug in net.links or proj["arch"] not in ("sm83", "z80", "mos6502"):
            raise NetworkError("AI documentation review is for local assembly ROM projects")
        if fn["status"] != "documented" or not fn["matched_source"]:
            raise NetworkError("only documented assembly can be reviewed")
        if net.store.one("SELECT 1 FROM claims WHERE function_id=?", fn["id"]):
            raise NetworkError("this routine is being worked on; wait for its helper to release it")
        return proj, fn

    def context(self, proj, fn):
        return digest({"assembly": self.net.assembly.context(proj, fn), "source": fn["matched_source"],
                       "asm": fn["asm"], "rom": self.net.cfg(proj).get("rom")})

    @staticmethod
    def dependency(fn):
        return digest({k: fn[k] for k in ("name", "vram", "rom_offset", "size", "target", "asm", "matched_source", "relocs")})

    def begin(self, agent, slug, function, *, kind="", model=""):
        proj, fn = self.target(slug, function)
        if fn["matched_agent_id"] == agent.id:
            raise NetworkError("use a fresh helper to review another helper's documentation")
        with self.net.store.tx() as db:
            db.execute("UPDATE agents SET origin='review' WHERE id=?", (agent.id,))
        self.active[agent.id] = {"slug": slug, "id": fn["id"], "name": fn["name"],
                                 "context": self.context(proj, fn), "dependencies": {}, "done": False,
                                 "reviewer": agent.name, "kind": kind, "model": model}

    def is_reviewer(self, agent):
        row = self.net.store.one("SELECT origin FROM agents WHERE id=?", agent.id)
        return agent.id in self.active or bool(row and row["origin"] == "review")

    def session(self, agent, slug):
        state = self.active.get(agent.id)
        if not state or state["slug"] != slug:
            raise NetworkError("start a dedicated AI documentation review first")
        if state["done"]:
            raise NetworkError("this review is already saved; stop here")
        return state

    def inputs(self, agent, slug):
        state = self.session(agent, slug)
        proj, fn = self.target(slug, state["name"])
        if self.context(proj, fn) != state["context"]:
            raise NetworkError("the documentation or its context changed; start a fresh review")
        xrefs, syms = self.net.xrefs(proj, fn["unit"]), self.net.symbols(proj["id"], fn["unit"])
        return json.dumps({"function": fn["name"], "review_context": state["context"],
                           "source": fn["matched_source"], "target_assembly": self.net._asm_text(fn, proj),
                           "platform": self.net.cfg(proj).get("platform"),
                           "calls": [syms.label(a) for a in sorted(xrefs["calls"].get(fn["vram"], ()))],
                           "called_by": [syms.label(a) for a in sorted(xrefs["called_by"].get(fn["vram"], ()))],
                           "checks": self.net.assembly.view(proj, fn).get("validation")}, indent=2)

    def read_function(self, agent, slug, function, start_line=0):
        state = self.session(agent, slug)
        fn, proj = self.net._function(function, slug), self.net._project(slug)
        # Read without producing compiler seeds or claiming neighbouring work.
        state["dependencies"][str(fn["id"])] = self.dependency(fn)
        lines = self.net._asm_text(fn, proj).splitlines()
        start = max(0, int(start_line or 0))
        return json.dumps({"function": fn["name"], "address": fn["vram"], "rom_offset": fn["rom_offset"],
                           "assembly": "\n".join(lines[start:start + 200]), "total_lines": len(lines),
                           "documented_source": fn["matched_source"]}, indent=2)

    def current(self, proj, fn, receipt):
        if fn["status"] != "documented" or self.context(proj, fn) != receipt["context"]:
            return False
        for fid, expected in receipt.get("dependencies", {}).items():
            row = self.net.store.one("SELECT * FROM functions WHERE id=? AND project_id=?", int(fid), proj["id"])
            if row is None or self.dependency(row) != expected:
                return False
        return True

    def submit(self, agent, slug, function, review_context, verdict, summary, evidence, concerns):
        state = self.session(agent, slug)
        proj, fn = self.target(slug, function)
        if fn["id"] != state["id"] or review_context != state["context"] or not self.current(proj, fn, state):
            raise NetworkError("review inputs changed or target differs; start a fresh review")
        if verdict not in VERDICTS:
            raise NetworkError("verdict must be supported, needs_changes or uncertain")
        if not isinstance(summary, str) or not 20 <= len(summary.strip()) <= 4000:
            raise NetworkError("give a plain-English summary of 20 to 4000 characters")
        for name, values in (("evidence", evidence), ("concerns", concerns)):
            if not isinstance(values, list) or len(values) > 12 or any(
                    not isinstance(s, str) or not 10 <= len(s.strip()) <= 2000 for s in values):
                raise NetworkError(f"{name} must contain up to 12 specific statements of 10 to 2000 characters")
        if not evidence or (verdict != "supported" and not concerns) or (verdict == "supported" and concerns):
            raise NetworkError("cite evidence; use uncertain or needs_changes when concerns remain")
        receipt = {k: state[k] for k in ("context", "dependencies", "reviewer", "kind", "model")}
        receipt |= {"verdict": verdict, "summary": summary.strip(), "evidence": evidence,
                    "concerns": concerns, "at": time.time()}
        with self.net.store.tx() as db:
            # Recheck under the write lock so a concurrent send-back/resplit cannot save a current-looking report.
            row = db.execute("SELECT * FROM functions WHERE id=?", (fn["id"],)).fetchone()
            project = db.execute("SELECT * FROM projects WHERE id=?", (proj["id"],)).fetchone()
            if row is None or not self.current(project, row, state):
                raise NetworkError("review inputs changed; start a fresh review")
            meta = json.loads(row["meta"] or "{}")
            meta["documentation_reviews"] = [*meta.get("documentation_reviews", []), receipt][-10:]
            db.execute("UPDATE functions SET meta=? WHERE id=?", (json.dumps(meta), fn["id"]))
            self.net._event(db, proj["id"], agent.id, "documentation_review", fn["name"])
        state["done"] = True
        return "AI review saved. Human review flags and accepted source are unchanged. Stop here."

    def view(self, proj, fn):
        reports = json.loads(fn["meta"] or "{}").get("documentation_reviews", [])
        return [{**r, "current": self.current(proj, fn, r)} for r in reversed(reports)]
