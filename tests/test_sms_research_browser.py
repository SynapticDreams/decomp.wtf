"""Actual browser controls use guarded HTTP routes; independent DOM fixtures exercise interleaved requests."""
from pathlib import Path

from .browser_check import run
from .research_browser import live, SCRIPTS
from .test_sms_annotation_subjects import project as fixture_project

project = fixture_project


def test_research_controls_create_all_kinds_review_and_preserve_subjects_over_real_http(project, tmp_path):
    net, slug = project
    live(net, slug, tmp_path)
    rows = net.store.all('SELECT * FROM corrections WHERE project_id=?', net.project_row(slug)['id'])
    assert {row['kind'] for row in rows} == {'code', 'data', 'table', 'operands', 'noreturn', 'record', 'pointers', 'split_pointers', 'number', 'mapping'}
    assert sum(row['undone_at'] is not None for row in rows) == 1
    note = net.store.one("SELECT * FROM notes WHERE text LIKE 'Authored browser note%'")
    assert len(note['text']) == 4000
    assert note['function_id'] is not None and note['annotation'] is note['evidence'] is note['subject'] is None
    assert net.store.one("SELECT COUNT(*) AS n FROM notes WHERE text LIKE 'Archived research v1:%'")['n'] == 2
    symbol = net.store.one('SELECT * FROM symbols WHERE evidence IS NOT NULL')
    assert net.inspect_annotations(slug, 'symbol', symbol['name'])['application'] == 'reviewed_research'


def test_research_controls_bound_pages_and_ignore_stale_previews_inspections_and_projects(tmp_path):
    page = (Path(__file__).resolve().parents[1] / 'src/decompnet/app/static/index.html').read_text()
    markup = page[page.index('<div id="smsResearch"'):page.index('<h3 class="sub" id="symHead"')]
    run(tmp_path, ['src/decompnet/app/static/' + script for script in SCRIPTS] + ['tests/browser/sms_research.js'],
        markup=markup, asynchronous=True)
