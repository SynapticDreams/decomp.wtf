"""Independent AI assessments of accepted assembly; never human approval or source edits."""
from __future__ import annotations

import json
import time

from ..network import NetworkError
from .assembly_work import digest


READ_TOOLS = {"get_documentation_review", "get_function", "read_data", "guide", "submit_documentation_review"}
COMMENT_TOOLS = READ_TOOLS - {"submit_documentation_review"} | {"submit_comment_revision"}
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

    def begin(self, agent, slug, function, *, kind="", model="", comments=False, candidate="", stop=None):
        proj, fn = self.target(slug, function)
        if not comments and fn["matched_agent_id"] == agent.id:
            raise NetworkError("use a fresh helper to review another helper's documentation")
        meta = json.loads(fn['meta'] or '{}')
        proposal = meta.get('comment_revision') or {}
        if candidate and (proposal.get('token') != candidate or proposal.get('base') != self.context(proj, fn)):
            raise NetworkError('the proposed comments changed; start a fresh review')
        if candidate and proposal.get('writer_id') == agent.id:
            raise NetworkError('a different helper must review the proposed comments')
        reports = self.view(proj, fn)
        if comments and not any(r['current'] and r['verdict'] == 'needs_changes' and r.get('followup') == 'comments' for r in reports[:1]):
            raise NetworkError('a current independent review must identify a comment-only correction first')
        with self.net.store.tx() as db:
            db.execute("UPDATE agents SET origin='review' WHERE id=?", (agent.id,))
        self.active[agent.id] = {"slug": slug, "id": fn["id"], "name": fn["name"],
                                 "context": self.context(proj, fn), "dependencies": {}, "done": False,
                                 "reviewer": agent.name, "kind": kind, "model": model,
                                 "comments": comments, "candidate": candidate, "stop": stop}

    def allowed_tools(self, agent):
        return COMMENT_TOOLS if self.active.get(agent.id, {}).get('comments') else READ_TOOLS

    def is_reviewer(self, agent):
        row = self.net.store.one("SELECT origin FROM agents WHERE id=?", agent.id)
        return agent.id in self.active or bool(row and row["origin"] == "review")

    def session(self, agent, slug):
        state = self.active.get(agent.id)
        if not state or state["slug"] != slug:
            raise NetworkError("start a dedicated AI documentation review first")
        if state.get('stop') is not None and state['stop'].is_set():
            raise NetworkError('the review was stopped; no changes can be saved')
        if state["done"]:
            raise NetworkError("this review is already saved; stop here")
        return state

    def inputs(self, agent, slug):
        state = self.session(agent, slug)
        proj, fn = self.target(slug, state["name"])
        if self.context(proj, fn) != state["context"]:
            raise NetworkError("the documentation or its context changed; start a fresh review")
        xrefs, syms = self.net.xrefs(proj, fn["unit"]), self.net.symbols(proj["id"], fn["unit"])
        routine = self.net._routine(proj, fn)
        proposal = json.loads(fn['meta'] or '{}').get('comment_revision') or {}
        source = proposal['source'] if state.get('candidate') else fn['matched_source']
        if state.get('candidate') and proposal.get('token') != state['candidate']:
            raise NetworkError('the proposed comments changed; start a fresh review')
        return json.dumps({"function": fn["name"], "review_context": state["context"],
                           "source": source, "target_assembly": self.net._asm_text(fn, proj),
                           "review_findings": self.view(proj, fn)[:1] if state.get('comments') else [],
                           "platform": self.net.cfg(proj).get("platform"),
                           "address": fn["vram"], "rom_offset": fn["rom_offset"], "bank": routine.bank,
                           "mapper": routine.mapper, "cartridge_profile": self.net.cfg(proj).get("sms_profile"),
                           "symbols": routine.symbols, "data_regions": routine.data,
                           "calls": [syms.label(a) for a in sorted(xrefs["calls"].get(fn["vram"], ()))],
                           "called_by": [syms.label(a) for a in sorted(xrefs["called_by"].get(fn["vram"], ()))],
                           "checks": self.net.assembly.view(proj, fn).get("validation")}, indent=2)

    def read_function(self, agent, slug, function, start_line=0):
        state = self.session(agent, slug)
        fn, proj = self.net._function(function, slug), self.net._project(slug)
        # Read without producing compiler seeds or claiming neighbouring work.
        state["dependencies"][str(fn["id"])] = self.dependency(fn)
        source = fn['matched_source']
        if state.get('candidate') and fn['id'] == state['id']:
            source = json.loads(fn['meta'] or '{}')['comment_revision']['source']
        lines = self.net._asm_text(fn, proj).splitlines()
        start = max(0, int(start_line or 0))
        return json.dumps({"function": fn["name"], "address": fn["vram"], "rom_offset": fn["rom_offset"],
                           "assembly": "\n".join(lines[start:start + 200]), "total_lines": len(lines),
                           "documented_source": source}, indent=2)

    def current(self, proj, fn, receipt):
        if fn["status"] != "documented" or self.context(proj, fn) != receipt["context"]:
            return False
        if receipt.get('candidate') and not receipt.get('applied'):
            proposal = json.loads(fn['meta'] or '{}').get('comment_revision') or {}
            if proposal.get('token') != receipt['candidate'] or proposal.get('base') != receipt['context']:
                return False
        for fid, expected in receipt.get("dependencies", {}).items():
            row = self.net.store.one("SELECT * FROM functions WHERE id=? AND project_id=?", int(fid), proj["id"])
            if row is None or self.dependency(row) != expected:
                return False
        return True

    def submit(self, agent, slug, function, review_context, verdict, summary, evidence, concerns, followup=""):
        state = self.session(agent, slug)
        if state.get('comments'):
            raise NetworkError('the writer can propose comments, not review or approve them')
        proj, fn = self.target(slug, function)
        if fn["id"] != state["id"] or review_context != state["context"] or not self.current(proj, fn, state):
            raise NetworkError("review inputs changed or target differs; start a fresh review")
        if verdict not in VERDICTS:
            raise NetworkError("verdict must be supported, needs_changes or uncertain")
        followup = followup or ('none' if verdict == 'supported' else 'evidence')
        if followup not in ('none', 'comments', 'evidence', 'layout') or (verdict == 'supported') != (followup == 'none') or (followup == 'comments' and verdict != 'needs_changes'):
            raise NetworkError('followup must be none for supported, comments for a specific comment-only correction, or evidence/layout')
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
                    "concerns": concerns, "followup": followup, "at": time.time()}
        if state.get('candidate'):
            receipt['candidate'] = state['candidate']
        with self.net.store.tx() as db:
            # Recheck under the write lock so a concurrent send-back/resplit cannot save a current-looking report.
            row = db.execute("SELECT * FROM functions WHERE id=?", (fn["id"],)).fetchone()
            project = db.execute("SELECT * FROM projects WHERE id=?", (proj["id"],)).fetchone()
            if row is None or not self.current(project, row, state):
                raise NetworkError("review inputs changed; start a fresh review")
            meta = json.loads(row["meta"] or "{}")
            if state.get('stop') is not None and state['stop'].is_set():
                raise NetworkError('the review was stopped')
            if state.get('candidate') and verdict == 'supported':
                proposal = meta['comment_revision']
                meta['comment_history'] = [*meta.get('comment_history', []),
                    {'source': row['matched_source'], 'at': time.time(), 'writer': proposal['writer']}][-5:]
                db.execute('UPDATE functions SET matched_source=?,matched_agent_id=? WHERE id=?',
                           (proposal['source'], proposal['writer_id'], fn['id']))
                changed = db.execute('SELECT * FROM functions WHERE id=?', (fn['id'],)).fetchone()
                receipt['context'] = self.context(project, changed)
                receipt['dependencies'] = dict(receipt['dependencies'])
                if str(fn['id']) in receipt['dependencies']:
                    receipt['dependencies'][str(fn['id'])] = self.dependency(changed)
                receipt['applied'] = True
                meta.setdefault('assembly_work', {})['validation'] = proposal['validation']
                meta.pop('comment_revision', None)
            if verdict == 'supported':
                meta.pop('documentation_followup', None)
            meta["documentation_reviews"] = [*meta.get("documentation_reviews", []), receipt][-10:]
            db.execute("UPDATE functions SET meta=? WHERE id=?", (json.dumps(meta), fn["id"]))
            self.net._event(db, proj["id"], agent.id, "documentation_review", fn["name"])
        state["done"] = True
        return "AI review saved. " + ('Validated comments applied after independent review. ' if receipt.get('applied') else 'Accepted source is unchanged. ') + 'Human review flags are unchanged. Stop here.'

    @staticmethod
    def code_lines(source):
        # Conservative lexical comparison: instructions, labels, strings and definitions must stay identical.
        # Treat apostrophes in Z80 register names (af') as code; never allow a comment to hide changed code.
        import re
        def code(line):
            quote, escaped = None, False
            for i, char in enumerate(line):
                if quote:
                    if escaped:
                        escaped = False
                    elif char == '\\':
                        escaped = True
                    elif char == quote:
                        quote = None
                elif char in '\"\'' and (char != "'" or i == 0 or not re.match(r'[A-Za-z0-9_]', line[i-1])):
                    quote = char
                elif char == ';':
                    return line[:i].strip()
            return line.strip()
        return tuple(part for line in source.splitlines() if (part := code(line)))

    def propose_comments(self, agent, slug, function, review_context, source):
        state = self.session(agent, slug)
        proj, fn = self.target(slug, function)
        if not state.get('comments') or fn['id'] != state['id'] or review_context != state['context'] or not self.current(proj, fn, state):
            raise NetworkError('the comment task changed; start a fresh writer session')
        if not isinstance(source, str) or len(source) > 65536 or source == fn['matched_source'] or self.code_lines(source) != self.code_lines(fn['matched_source']):
            raise NetworkError('change comments only; preserve every instruction, label, definition and string')
        judge = self.net._asm_judge(proj)
        self.net.sms.require(row=proj)
        if not judge.available():
            raise NetworkError('install the project assembler before automatically correcting comments')
        routine = self.net._routine(proj, fn)
        try:
            verdict = judge.judge(routine, source)
        except judge.AsmError as exc:
            raise NetworkError(str(exc)) from None
        if not verdict.ok or verdict.same != verdict.size or verdict.size != len(routine.code):
            return 'Not saved: assembly validation failed.\n' + '\n'.join(str(p)[:2000] for p in verdict.problems[:12])
        proposal = {'token': digest([state['context'], source]), 'base': state['context'], 'source': source,
                    'writer': agent.name, 'writer_id': agent.id, 'at': time.time(),
                    'validation': self.net.assembly.receipt(proj, fn, routine, source, verdict)}
        with self.net.store.tx() as db:
            row = db.execute('SELECT * FROM functions WHERE id=?', (fn['id'],)).fetchone()
            project = db.execute('SELECT * FROM projects WHERE id=?', (proj['id'],)).fetchone()
            self.session(agent, slug)
            if row is None or not self.current(project, row, state):
                raise NetworkError('the comment task changed while validating; no proposal saved')
            meta = json.loads(row['meta'] or '{}'); meta['comment_revision'] = proposal
            db.execute('UPDATE functions SET meta=? WHERE id=?', (json.dumps(meta), fn['id']))
            self.net._event(db, proj['id'], agent.id, 'comment_proposal', fn['name'])
        state['done'] = True
        return 'Validated comment proposal saved for independent review. Accepted source is unchanged. Stop here.'

    def view(self, proj, fn):
        reports = json.loads(fn["meta"] or "{}").get("documentation_reviews", [])
        return [{**r, "current": self.current(proj, fn, r)} for r in reversed(reports)]

    def latest(self, proj, fn):
        reports = json.loads(fn['meta'] or '{}').get('documentation_reviews', [])
        return {**reports[-1], 'current': self.current(proj, fn, reports[-1])} if reports else None
