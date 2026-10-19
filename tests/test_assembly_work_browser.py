"""Assembly receipts and drawer launch controls exercised in Chromium with authored data."""
from .browser_check import run
from .test_assembly_work import work  # noqa: F401


def test_assembly_checklist_distinguishes_pending_stale_and_unchecked_results(tmp_path):
    run(tmp_path, ['src/decompnet/app/static/assembly-work.js', 'tests/browser/assembly_work.js'])


def test_assembly_drawer_can_resume_defer_and_launch_on_its_own_track(work, tmp_path, monkeypatch):  # noqa: F811
    from .assembly_browser import live
    net, agent, _ = work
    net.document_function(agent, 'authored', 'First', '; authored\nFirst: ret')
    manager = live(net, tmp_path, monkeypatch)
    (session,) = manager.sessions.values()
    assert session.options['pin'] == 'First' and session.options['track'] == 'asm'
    assert not session.options['polish'] and not session.options.get('lean')
    fn = net._function('First', 'authored')
    assert fn['status'] == 'asm' and net.assembly.view(net._project('authored'), fn)['deferred']
