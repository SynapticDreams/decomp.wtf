"""Bounded, resumable review queues. Only task-owned helpers are stopped by batch controls."""
from __future__ import annotations

import json
import threading
import time
import uuid
from collections import Counter

from ..network import NetworkError
from .assembly_work import digest

FINAL = {'reviewed', 'corrected', 'needs_evidence', 'needs_layout', 'failed'}


def report_key(receipt):
    return digest([receipt['at'], receipt['context'], receipt.get('candidate'), receipt['verdict']])


class BatchPaused(Exception):
    pass


class ReviewBatches:
    def __init__(self, manager):
        self.manager, self.net = manager, manager.net
        self.lock = threading.RLock()
        self.active = {}
        self.resolve = lambda role: {'kind': role['kind'], 'options': {k: v for k, v in role.items() if k in ('model', 'effort')}}

    def project(self, slug):
        proj = self.net._project(slug)
        if self.net.fork_slug(slug) or slug in self.net.links or proj['arch'] not in ('z80', 'sm83', 'mos6502'):
            raise NetworkError('batch documentation review is for local assembly ROM projects')
        return proj

    def load(self, slug):
        proj = self.project(slug)
        row = self.net.store.one('SELECT value FROM settings WHERE key=?', f'review_batch:{proj["id"]}')
        batch = json.loads(row['value']) if row else None
        return batch if batch and batch.get('slug') == slug and batch.get('input') == digest(self.net.cfg(proj).get('rom')) else None

    def save(self, batch):
        with self.lock, self.net.store.tx() as db:
            db.execute('INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',
                       (f'review_batch:{batch["project"]}', json.dumps(batch)))

    def running(self, slug):
        with self.lock:
            return slug in self.active and not self.active[slug]['stop'].is_set()

    def view(self, slug):
        with self.lock:
            batch = self.load(slug)
            if not batch:
                return None
            if slug not in self.active and batch['state'] == 'running':
                batch['state'], batch['reason'] = 'paused', 'App restarted. Resume explicitly to continue.'
            counts = Counter(item['status'] for item in batch['items'])
            for item in batch['items']:
                if item['status'] in FINAL - {'failed'}:
                    fn = self.net.store.one('SELECT * FROM functions WHERE id=? AND project_id=?', item['id'], batch['project'])
                    receipt = self.net.documentation_review.latest(self.net._project(slug), fn) if fn else None
                    item['outdated'] = not receipt or not receipt['current'] or report_key(receipt) != item.get('receipt')
            batch['counts'] = {key: counts[key] for key in ('reviewed', 'corrected', 'needs_evidence', 'needs_layout', 'failed', 'pending')}
            batch['counts']['outdated'] = sum(bool(i.get('outdated')) for i in batch['items'])
            batch['total'] = len(batch['items'])
            return batch

    @staticmethod
    def role(given):
        if not isinstance(given, dict) or given.get('kind') not in ('api', 'claude', 'codex', 'opencode', 'antigravity'):
            raise NetworkError('choose an installed helper or saved API endpoint for each role')
        out = {k: str(given[k])[:300] for k in ('kind', 'model', 'effort', 'endpoint') if given.get(k)}
        if out.get('model') == 'tiered' or (out['kind'] == 'api' and not out.get('endpoint')):
            raise NetworkError('choose one model or saved API endpoint per role')
        return out

    def start(self, slug, reviewer, writer, *, limits=None, fix_comments=True, resume=False):
        proj = self.project(slug)
        reviewer, writer = self.role(reviewer), self.role(writer)
        # Resolve credentials at launch only. Secrets are never stored in batch state or API responses.
        self.resolve(reviewer); self.resolve(writer)
        if limits is not None and not isinstance(limits, dict):
            raise NetworkError('limits must be an object with functions, sessions, minutes and tokens')
        limits = limits or {}
        bounds = {'functions': (100, 1, 500), 'sessions': (100, 1, 1000), 'minutes': (30, 1, 240), 'tokens': (1000000, 1000, 100000000)}
        if set(limits) - set(bounds):
            raise NetworkError('supported limits are functions, sessions, minutes and tokens')
        checked = {}
        for key, (default, lo, hi) in bounds.items():
            value = limits.get(key, default)
            if isinstance(value, bool) or not isinstance(value, int) or not lo <= value <= hi:
                raise NetworkError(f'{key} limit must be an integer between {lo} and {hi}')
            checked[key] = value
        with self.lock:
            if slug in self.active:
                raise NetworkError('a review batch is already running or stopping for this project')
            old = self.view(slug) if resume else None
            if resume and not old:
                raise NetworkError('there is no review batch to resume')
            if old:
                batch = old
                # Preserve finished follow-ups; unfinished stages inspect saved reports/proposals again.
                for item in batch['items']:
                    if item['status'] not in FINAL or item.get('outdated'):
                        item['status'] = 'pending'
            else:
                items = []
                for fn in self.net.store.all("SELECT * FROM functions WHERE project_id=? AND status='documented' ORDER BY vram,id", proj['id']):
                    receipt = self.net.documentation_review.latest(proj, fn)
                    latest = receipt if receipt and receipt['current'] else None
                    if latest and latest['verdict'] == 'supported':
                        continue
                    if not json.loads(fn['meta'] or '{}').get('sample') and not receipt:
                        continue
                    items.append({'id': fn['id'], 'name': fn['name'], 'status': 'pending', 'message': '', 'correction_attempted': False})
                    if len(items) >= checked['functions']:
                        break
                batch = {'id': uuid.uuid4().hex, 'project': proj['id'], 'slug': slug, 'input': digest(self.net.cfg(proj).get('rom')),
                         'created_at': time.time(), 'items': items}
            batch.update(state='running', reason='', reviewer=reviewer, writer=writer, fix_comments=bool(fix_comments),
                         limits=checked, sessions=0, tokens=0, usd=0, started_at=time.time(), current='', helper='')
            control = {'stop': threading.Event(), 'batch': batch}
            self.active[slug] = control
            self.save(batch)
            threading.Thread(target=self.run, args=(batch, control), daemon=True, name=f'review-batch-{batch["id"][:8]}').start()
        return self.view(slug)

    def stop(self, slug):
        with self.lock:
            control = self.active.get(slug)
            if control:
                control['stop'].set()
                helper = control['batch'].get('helper')
                if helper:
                    self.manager.stop(helper)
        return self.view(slug)

    def stop_all(self):
        for slug in list(self.active):
            self.stop(slug)

    def guard(self, batch, control, session=None):
        if control['stop'].is_set():
            raise BatchPaused('Stopped. Saved work is retained; resume to continue.')
        if time.time() - batch['started_at'] >= batch['limits']['minutes'] * 60:
            if session:
                self.manager.stop(session.id)
            raise BatchPaused('Time limit reached. Saved work is retained.')
        if batch['tokens'] + (session.tokens if session else 0) >= batch['limits']['tokens']:
            if session:
                self.manager.stop(session.id)
            raise BatchPaused('Reported token limit reached. Usage may omit tokens a CLI does not report.')
        if self.manager.over_budget(batch['slug']) is not None:
            if session:
                self.manager.stop(session.id)
            raise BatchPaused('Project spending limit reached.')

    def launch(self, batch, control, item, role, track, candidate=''):
        self.guard(batch, control)
        if batch['sessions'] >= batch['limits']['sessions']:
            raise BatchPaused('Helper session limit reached. Resume with a new allowance to continue.')
        setup = self.resolve(role)
        options = dict(setup.get('options') or {}) | {'pin': item['name'], 'track': track, 'polish': False,
                    'review_batch': batch['id'], 'review_candidate': candidate}
        # Serialize launching with Stop so a stopped batch cannot launch another helper in the gap.
        with self.lock:
            self.guard(batch, control)
            sid, = self.manager.start(setup['kind'], batch['slug'], 1, options)
            batch['helper'] = sid; batch['sessions'] += 1
            self.save(batch)
        session = self.manager.sessions[sid]
        try:
            while not session.stop.wait(.1):
                self.guard(batch, control, session)
            self.guard(batch, control)
            if session.state == 'error':
                raise NetworkError(session.error or 'helper failed')
        finally:
            batch['tokens'] += session.tokens
            batch['usd'] += session.usd
            batch['helper'] = ''
            self.save(batch)

    def followup(self, proj, fn, receipt, message=None):
        kind = 'layout' if receipt.get('followup') == 'layout' else 'evidence'
        text = message or '\n'.join([receipt['summary'], *receipt.get('concerns', [])])
        token = digest([receipt['context'], receipt.get('at'), receipt.get('candidate'), text])
        with self.net.store.tx() as db:
            row = db.execute('SELECT * FROM functions WHERE id=?', (fn['id'],)).fetchone()
            project = db.execute('SELECT * FROM projects WHERE id=?', (proj['id'],)).fetchone()
            if row is None or not self.net.documentation_review.current(project, row, receipt):
                raise NetworkError('review context changed before queuing follow-up; run a fresh review')
            meta = json.loads(row['meta'] or '{}')
            if meta.get('documentation_followup', {}).get('token') != token:
                meta['documentation_followup'] = {'token': token, 'kind': kind, 'text': text[:16000],
                    'context': receipt['context'], 'dependencies': receipt.get('dependencies', {}), 'at': time.time(),
                    **({'candidate': receipt['candidate']} if receipt.get('candidate') and not receipt.get('applied') else {})}
                db.execute('UPDATE functions SET meta=? WHERE id=?', (json.dumps(meta), fn['id']))
                db.execute('INSERT INTO notes(project_id,function_id,agent_id,text,created_at) VALUES(?,?,?,?,?)',
                           (proj['id'], fn['id'], None, f'AI review follow-up ({kind}):\n{text[:16000]}', time.time()))
                self.net._event(db, proj['id'], None, 'review_followup', fn['name'])
        return f'needs_{kind}', text[:2000]

    def process(self, batch, control, item):
        proj = self.project(batch['slug'])
        fn = self.net.store.one('SELECT * FROM functions WHERE id=? AND project_id=?', item['id'], proj['id'])
        if fn is None or fn['status'] != 'documented':
            raise NetworkError('routine was removed or is no longer documented')
        item['name'] = fn['name']
        self.net.documentation_review.target(batch['slug'], fn['name'])
        latest = self.net.documentation_review.latest(proj, fn)
        receipt = latest if latest and latest['current'] else None
        proposal = json.loads(fn['meta'] or '{}').get('comment_revision') or {}
        if proposal and proposal.get('base') == self.net.documentation_review.context(proj, fn) and not item.get('proposal_reviewed'):
            item['status'] = 'checking'; self.save(batch)
            self.launch(batch, control, item, batch['reviewer'], 'asm_review', proposal['token'])
            item['proposal_reviewed'] = True
            return self.finish(batch, item)
        if not receipt or (receipt['verdict'] == 'needs_changes' and not receipt.get('followup')):
            item['status'] = 'reviewing'; self.save(batch)
            self.launch(batch, control, item, batch['reviewer'], 'asm_review')
            fn = self.net._function(item['name'], batch['slug'])
            latest = self.net.documentation_review.latest(proj, fn)
            receipt = latest if latest and latest['current'] else None
        if not receipt:
            raise NetworkError('no current review was saved; source/context may have changed')
        if receipt['verdict'] == 'supported':
            item.update(status='corrected' if receipt.get('applied') else 'reviewed', message=receipt['summary'])
        elif receipt.get('followup') == 'comments' and batch['fix_comments'] and not item['correction_attempted']:
            item.update(status='correcting'); self.save(batch)
            self.launch(batch, control, item, batch['writer'], 'asm_comment_fix')
            fn = self.net._function(item['name'], batch['slug'])
            proposal = json.loads(fn['meta'] or '{}').get('comment_revision') or {}
            if not proposal or proposal.get('base') != self.net.documentation_review.context(proj, fn):
                raise NetworkError('writer did not leave a current validated comment proposal')
            item['correction_attempted'] = True
            item['status'] = 'checking'; self.save(batch)
            self.launch(batch, control, item, batch['reviewer'], 'asm_review', proposal['token'])
            item['proposal_reviewed'] = True
            self.finish(batch, item)
        else:
            item['status'], item['message'] = self.followup(proj, fn, receipt)

    def finish(self, batch, item):
        proj, fn = self.project(batch['slug']), self.net._function(item['name'], batch['slug'])
        latest = self.net.documentation_review.latest(proj, fn)
        receipt = latest if latest and latest['current'] else None
        if not receipt:
            raise NetworkError('no current independent review of the proposed comments was saved')
        if receipt.get('applied') and receipt['verdict'] == 'supported':
            item.update(status='corrected', message=receipt['summary'])
        else:
            item['status'], item['message'] = self.followup(proj, fn, receipt,
                'Comment proposal was not independently supported; accepted source was preserved.\n' +
                receipt['summary'] + '\n' + '\n'.join(receipt.get('concerns', [])))

    def run(self, batch, control):
        try:
            processed = 0
            for item in batch['items']:
                if item['status'] in FINAL:
                    continue
                if processed >= batch['limits']['functions']:
                    raise BatchPaused('Routine limit reached. Resume with a new allowance to continue.')
                self.guard(batch, control)
                processed += 1
                batch['current'] = item['name']; self.save(batch)
                try:
                    self.process(batch, control, item)
                    fn = self.net._function(item['name'], batch['slug'])
                    receipt = self.net.documentation_review.latest(self.project(batch['slug']), fn)
                    item['receipt'] = report_key(receipt) if receipt else ''
                except NetworkError as exc:
                    item.update(status='failed', message=str(exc)[:2000])
                self.save(batch)
            batch['state'] = 'complete'
        except BatchPaused as exc:
            batch['state'], batch['reason'] = 'paused', str(exc)
        except Exception as exc:
            batch['state'], batch['reason'] = 'paused', f'{type(exc).__name__}: {str(exc)[:1000]}'
        finally:
            with self.lock:
                helper = batch.get('helper')
                if helper:
                    self.manager.stop(helper)
                batch['helper'], batch['current'] = '', ''
                self.save(batch)
                self.active.pop(batch['slug'], None)
