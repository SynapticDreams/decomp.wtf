"""Notes and symbols retain original subjects, distinct address spaces and operator authority."""
from pathlib import Path

import pytest

from decompnet.app.engine import RomNetwork
from decompnet.app import annotation_archives as archives, sms_annotation_context as context
from decompnet.network import NetworkError
from decompnet.rom.annotations import dump
from .annotation_fixture import annotation, evidence
from .test_sms_resplit_source_check import project as fixture_project

project = fixture_project
TEXT = 'The authored consumer uses this record layout; its runtime memory contents remain unobserved.'


def symbol(net, slug):
    return net.store.one('SELECT name FROM functions WHERE project_id=? AND rom_offset=512', net.project_row(slug)['id'])['name']


def put(net, slug, agent, kind, *, value=None, proof=None, key=None, text=TEXT, function=None):
    args = {'annotation': value, 'evidence': proof or evidence(), 'apply': False}
    if kind == 'symbol':
        name = key or symbol(net, slug)
        preview = net.annotate_symbol(agent, slug, name, **args)
        return net.annotate_symbol(agent, slug, name, **{**args, 'apply': True, 'expected_plan': preview['plan']})
    preview = net.add_note(agent, slug, text, function, note_id=key, **args)
    return net.add_note(agent, slug, text, function, note_id=key,
                        **{**args, 'apply': True, 'expected_plan': preview['plan']})


def review(net, slug, kind, key, *, ok=True, clear=False):
    preview = net.review_annotation(slug, kind, key, ok=ok, clear=clear)
    return net.review_annotation(slug, kind, key, ok=ok, clear=clear, apply=True, expected_plan=preview['plan'])


@pytest.mark.parametrize('kind', ['note', 'symbol'])
@pytest.mark.parametrize('space', [None, 'rom', 'wram', 'cart_ram'])
def test_notes_and_symbols_bind_full_subjects_and_reload_without_inventing_ram_contents(project, kind, space):
    net, slug = project
    agent, _ = net.local_agent('subject_writer')
    value = annotation() if space else None
    if value:
        value['target']['space'] = space
    before = context.guard(net, net.project_row(slug))
    args = {'annotation': value, 'evidence': evidence(), 'apply': False}
    preview = net.add_note(agent, slug, TEXT, **args) if kind == 'note' else net.annotate_symbol(agent, slug, symbol(net, slug), **args)
    assert not preview['applied'] and preview['record']['binding'] == 'current'
    assert context.guard(net, net.project_row(slug)) == before
    stored = put(net, slug, agent, kind, value=value)['record']
    assert stored['application'] == 'pending_review' and not stored['discovery']
    saved = stored['subject']['value']
    assert stored['evidence']['value']['subject_sha256'] == context.digest(saved)
    assert saved['entity']['kind'] == kind
    assert saved['mapping']['profile']['mapper'] == 'sega'
    if space in ('wram', 'cart_ram'):
        assert saved['source'] == {'space': space, 'contents': 'unobserved'}
    elif space:
        assert saved['source']['space'] == 'rom' and saved['source']['sha256']
    else:
        assert saved['source'] is None and stored['annotation']['value'] is None
    path = net.store.conn.execute('PRAGMA database_list').fetchone()[2]
    net.store.conn.close()
    loaded = RomNetwork(path, net.workspace)
    inspected = loaded.inspect_annotations(slug, kind, stored['key'])
    assert inspected['subject']['raw'] == stored['subject']['raw'] and inspected['binding'] == 'current'
    assert inspected['annotation']['value'] == value
    approved = review(loaded, slug, kind, stored['key'])['record']
    assert approved['application'] == 'reviewed_research' and not approved['discovery']
    assert not loaded._hints(loaded.project_row(slug))['data']


@pytest.mark.parametrize('kind', ['note', 'symbol'])
def test_metadata_replacement_and_detachment_archive_original_subject_and_receipts(project, kind):
    net, slug = project
    agent, _ = net.local_agent('archive_writer')
    original = put(net, slug, agent, kind, value=annotation())['record']
    original = review(net, slug, kind, original['key'])['record']
    replacement = annotation(); replacement['target']['offset'] += 64
    changed = put(net, slug, agent, kind, key=original['key'], value=replacement)['record']
    assert changed['application'] == 'pending_review'
    archived = net.store.one('SELECT * FROM notes WHERE text LIKE ? ORDER BY id DESC', archives.PREFIX + '%')
    assert archived['annotation'] == original['annotation']['raw']
    assert archived['evidence'] == original['evidence']['raw'] and archived['subject'] == original['subject']['raw']
    assert net.inspect_annotations(slug, 'note', archived['id'])['application'] == 'archived'
    with pytest.raises(NetworkError, match='read-only'):
        net.review_annotation(slug, 'note', archived['id'], ok=True)
    detached = review(net, slug, kind, changed['key'], clear=True)['record']
    assert detached['application'] == 'legacy_unknown'
    assert detached['annotation']['raw'] is detached['evidence']['raw'] is detached['subject']['raw'] is None
    last = net.store.one('SELECT * FROM notes WHERE text LIKE ? ORDER BY id DESC', archives.PREFIX + '%')
    assert last['subject'] == changed['subject']['raw'] and last['annotation'] == changed['annotation']['raw']


def test_full_length_notes_and_large_valid_record_payloads_fit_guarded_request_framing(project):
    net, slug = project
    agent, _ = net.local_agent('large_writer')
    value = annotation()
    value['target']['size'] = 256
    value['spec'] = {'count': 1, 'stride': 256, 'overlap': 'reject', 'fields': [
        {'name': f'field_{i}_' + 'x' * 48, 'offset': i, 'type': 'u8'} for i in range(200)]}
    assert len(dump(value)) > 4096
    fn = symbol(net, slug)
    before = tuple(net.store.one('SELECT target,size,status FROM functions WHERE name=?', fn))
    item = put(net, slug, agent, 'note', value=value, text='x' * 4000)['record']
    assert len(item['text']) == 4000 and item['annotation']['value'] == value
    preview = net.correct_split(agent, slug, 'record', '', TEXT, annotation=value, apply=False)
    assert not preview['applied'] and preview['correction']['annotation']['value'] == value
    assert tuple(net.store.one('SELECT target,size,status FROM functions WHERE name=?', fn)) == before


@pytest.mark.parametrize('kind', ['note', 'symbol'])
def test_changed_inputs_make_research_unavailable_but_opaque_metadata_can_be_detached(project, kind):
    net, slug = project
    agent, _ = net.local_agent('unavailable_writer')
    item = put(net, slug, agent, kind, value=annotation())['record']
    proj = net.project_row(slug)
    path = Path(proj['root']) / net.cfg(proj)['rom']['file']
    original = path.read_bytes(); path.unlink()
    assert net.inspect_annotations(slug, kind, item['key'])['application'] == 'unavailable'
    with pytest.raises(NetworkError):
        net.review_annotation(slug, kind, item['key'], ok=True)
    result = review(net, slug, kind, item['key'], clear=True)
    assert result['record']['application'] == 'legacy_unknown'
    archived = net.inspect_annotations(slug, 'note', result['archive_id'])
    assert archived['subject']['raw'] == item['subject']['raw'] and archived['application'] == 'archived'
    path.write_bytes(original)


def test_orphan_note_subject_retains_its_original_attachment_without_inventing_a_function(project):
    net, slug = project
    agent, _ = net.local_agent('orphan_subject_writer')
    pid = net.project_row(slug)['id']
    cid = net.store.conn.execute('INSERT INTO notes(project_id,function_id,text) VALUES(?,65535,?)', (pid, TEXT)).lastrowid
    item = put(net, slug, agent, 'note', key=cid)['record']
    assert item['subject']['value']['entity']['function_id'] == 65535
    assert item['subject']['value']['entity']['function'] is None
    assert item['subject']['value']['source'] is None and item['binding'] == 'current'
