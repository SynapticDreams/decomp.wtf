"""Research contexts bind immutable source bytes rather than upload timestamps or display names."""
from pathlib import Path

import pytest

from decompnet.app import sms_annotation_context as context
from decompnet.network import NetworkError
from .sms_wla_fixture import bank_zero_layout
from .test_sms_annotation_subjects import project as fixture_project, put, review, symbol
from .annotation_fixture import annotation

project = fixture_project


def test_declared_symbol_sources_support_all_research_records_and_ignore_presentation_metadata(project):
    net, slug = project
    agent, _ = net.local_agent('source_writer')
    proj = net.project_row(slug)
    image = (Path(proj['root']) / net.cfg(proj)['rom']['file']).read_bytes()
    layout = bank_zero_layout(image)
    net.import_symbols(slug, '[labels]\n00:0200 _LABEL_200_\n', 'fixture.sym', layout=layout)
    before = context.load(net, slug)[4]
    assert type(net.cfg(net.project_row(slug))['symbol_file']['at']) is float
    note = put(net, slug, agent, 'note', value=annotation())['record']
    sym = put(net, slug, agent, 'symbol', value=annotation())['record']
    proposal = net.correct_split(agent, slug, 'code', '00:0200', 'The authored source declares this existing entry.', apply=False)
    assert proposal['correction']['binding'] == 'current'
    review(net, slug, 'note', note['key'])
    review(net, slug, 'symbol', sym['key'])
    net._update_cfg(slug, lambda cfg: cfg['symbol_file'].update(at=1234.5, **{'from': 'other-display-name.sym'}))
    assert context.load(net, slug)[4] == before
    assert net.inspect_annotations(slug, 'note', note['key'])['application'] == 'reviewed_research'
    assert net.inspect_annotations(slug, 'symbol', symbol(net, slug))['application'] == 'reviewed_research'
    net.import_symbols(slug, '[labels]\n00:0200 _LABEL_200_\n00:0300 AnotherLabel\n', 'fixture.sym', layout=layout)
    assert context.load(net, slug)[4] != before
    assert net.inspect_annotations(slug, 'note', note['key'])['application'] == 'stale'


def test_changed_or_missing_source_bundle_is_unavailable_without_erasing_original_evidence(project):
    from decompnet.rom import wla_bundle
    net, slug = project
    agent, _ = net.local_agent('missing_source_writer')
    proj = net.project_row(slug)
    image = (Path(proj['root']) / net.cfg(proj)['rom']['file']).read_bytes()
    net.import_symbols(slug, '[labels]\n00:0200 _LABEL_200_\n', 'fixture.sym', layout=bank_zero_layout(image))
    item = put(net, slug, agent, 'note', value=annotation())['record']
    reference = net.cfg(net.project_row(slug))['symbol_file']
    path = wla_bundle.path(Path(proj['root']), reference)
    original = path.read_bytes()
    path.write_bytes(b'authored changed bundle')
    inspected = net.inspect_annotations(slug, 'note', item['key'])
    assert inspected['application'] == 'unavailable' and inspected['subject']['raw'] == item['subject']['raw']
    with pytest.raises(NetworkError):
        net.review_annotation(slug, 'note', item['key'], ok=True)
    path.write_bytes(original)
    assert net.inspect_annotations(slug, 'note', item['key'])['binding'] == 'current'
