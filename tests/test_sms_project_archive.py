"""Project-level saved work stays recoverable without inventing a function association."""
import base64
import hashlib
import json
from pathlib import Path

import pytest

from decompnet.app import banked_resplit_archive as archive, banked_resplit_state as state
from decompnet.network import NetworkError

from .test_sms_profile_migration import project as fixture_project, snapshot

project = fixture_project
TEXT = ('Authored project evidence\r\n' * 1500) + '😀 <img src=x> preserved'


@pytest.fixture
def saved(project):
    net, slug = project
    proj = net.project_row(slug)
    root = Path(proj['root'])
    for name, content in [('headers/raw.bin', b'\x00\xff\x10'), ('unit/fixture.h', b'#define AUTHORED 7\r\n')]:
        path = root / name
        path.parent.mkdir(exist_ok=True)
        path.write_bytes(content)
    net._update_cfg(slug, lambda cfg: cfg.update(private_fixture_secret='must-not-be-exported', compiler={
        **cfg['compiler'], 'include_dirs': ['headers'], 'units': {'authored-unit': {'include_dirs': ['unit']}}}))
    with net.store.tx() as db:
        db.execute('DELETE FROM functions WHERE project_id=?', (proj['id'],))
        note = db.execute('INSERT INTO notes(project_id,text) VALUES(?,?)', (proj['id'], TEXT)).lastrowid
        orphan = db.execute('INSERT INTO notes(project_id,function_id,text) VALUES(?,424242,?)',
                            (proj['id'], 'Authored evidence with an unknown former target')).lastrowid
        for i in range(30):
            db.execute('INSERT INTO notes(project_id,text) VALUES(?,?)', (proj['id'], f'Authored note {i}'))
        db.execute("INSERT INTO notes(function_id,text) VALUES(424243,'Unattributed note')")
        db.execute("INSERT INTO attempts(function_id,source) VALUES(424244,'Unattributed source')")
        db.execute("INSERT INTO claims(function_id,agent_id) VALUES(424245,1)")
        db.execute("INSERT INTO context_versions(project_id,version,unit,header) VALUES(?,500,'authored-unit',?)",
                   (proj['id'], '#define UNIT_VALUE 7\r\n'))
        db.execute("INSERT INTO corrections(project_id,kind,rom_offset,count,reason) VALUES(?,'data',16384,1,'Authored correction')",
                   (proj['id'],))
        db.execute("INSERT OR REPLACE INTO data_regions VALUES(?,20480,16,'data','Authored saved region')", (proj['id'],))
    result = net.resplit_banked(slug, apply=True, log=lambda *_: None)
    hid = result['history_id']
    with net.store.tx() as db:
        db.execute('DELETE FROM notes WHERE id=?', (note,))
    return net, slug, hid, note, orphan


def test_project_note_context_and_binary_dependencies_are_recoverable_after_new_work_blocks_undo(saved):
    net, slug, hid, note, orphan = saved
    before = snapshot(net, slug)
    with pytest.raises(NetworkError, match='changed after resplit'):
        net.undo_resplit(slug, hid)
    listing = archive.read(net, slug, hid)
    assert listing['functions'] == [] and listing['project_context_available']
    options, offset = [], 0
    while offset is not None:
        page = archive.read(net, slug, hid, scope='project', offset=offset)
        assert 'function' not in page and len(page['items']) <= 25
        assert TEXT not in json.dumps(page) and 'Unattributed' not in json.dumps(page)
        options.extend(page['items'])
        offset = page['next_offset']
    assert len(options) > 25 and len({item['key'] for item in options}) == len(options)
    chunks, offset = [], 0
    while offset is not None:
        part = archive.read(net, slug, hid, scope='project', item=f'note:{note}', start=offset)
        assert part['sha256'] == hashlib.sha256(TEXT.encode()).hexdigest()
        chunks.append(part['text'])
        offset = part['next_start']
    assert ''.join(chunks) == TEXT and part['filename'].endswith(f'_note_{note}.txt')
    assert part['item']['provenance']['association'] == 'project'
    unknown = archive.read(net, slug, hid, scope='project', item=f'note:{orphan}')
    assert unknown['item']['provenance']['function_id'] == 424242
    assert unknown['item']['provenance']['association'] == 'unknown-former-function'
    bodies = {item['key']: archive.read(net, slug, hid, scope='project', item=item['key'], limit=262144)['text']
              for item in options if not item['key'].startswith('note:')}
    assert 'must-not-be-exported' not in json.dumps(bodies)
    assert json.loads(bodies['compiler'])['units']['authored-unit']['include_dirs'] == ['unit']
    assert bodies['header:500'] == '#define UNIT_VALUE 7\r\n'
    assert any(json.loads(value).get('why') == 'Authored saved region' for key, value in bodies.items() if key.startswith('data:'))
    assert any(json.loads(value).get('reason') == 'Authored correction' for key, value in bodies.items() if key.startswith('correction:'))
    bundle = json.loads(bodies['dependencies'])
    assert 'prior acceptance context is not established' in bundle['capture_point']
    files = [file for directory in bundle['bundle']['directories'] for file in directory['files']]
    assert {base64.b64decode(file['content']['$blob']) for file in files} == {b'\x00\xff\x10', b'#define AUTHORED 7\r\n'}
    assert json.loads(bodies['claims']) == []  # Projectless old references were never attributed to this project.
    assert snapshot(net, slug) == before and not net.store.conn.in_transaction
    assert net.store.one('SELECT source FROM attempts WHERE function_id=424244')['source'] == 'Unattributed source'


@pytest.mark.parametrize('values', [{'scope': 'wrong'}, {'scope': 'project', 'function_id': 1},
    {'scope': 'project', 'item': 'accepted'}, {'scope': 'project', 'item': 'attempt:1'},
    {'scope': 'project', 'item': 'note:424243'}, {'scope': 'project', 'item': 'data:-1'},
    {'scope': 'project', 'start': 1}, {'scope': 'project', 'offset': 999999}])
def test_project_recovery_rejects_ambiguous_or_unattributed_selection(saved, values):
    net, slug, hid, _note, _orphan = saved
    before = snapshot(net, slug)
    with pytest.raises(NetworkError):
        archive.read(net, slug, hid, **values)
    assert snapshot(net, slug) == before


@pytest.mark.parametrize('table', ['notes', 'symbols', 'data_regions', 'corrections', 'context_versions', 'attempts', 'claims'])
def test_project_recovery_refuses_foreign_or_unowned_records_even_in_a_rewritten_snapshot(saved, table):
    net, slug, hid, _note, _orphan = saved
    row = net.store.one('SELECT * FROM resplit_history WHERE id=?', hid)
    old = state.decode(row['before_state'], row['before_digest'])
    if table in ('attempts', 'claims'):
        old['tables'][table].append({'function_id': 424244})
    elif old['tables'][table]:
        old['tables'][table][0]['project_id'] += 1
    else:
        old['tables'][table].append({'project_id': old['project']['id'] + 1})
    payload, digest = state.encode(old)
    with net.store.tx() as db:
        db.execute('UPDATE resplit_history SET before_state=?,before_digest=? WHERE id=?', (payload, digest, hid))
    with pytest.raises(NetworkError, match='ownership|another project'):
        archive.read(net, slug, hid, scope='project')


def test_legacy_null_note_is_explicit_in_project_provenance(saved):
    net, slug, hid, note, _orphan = saved
    row = net.store.one('SELECT * FROM resplit_history WHERE id=?', hid)
    old = state.decode(row['before_state'], row['before_digest'])
    next(value for value in old['tables']['notes'] if value['id'] == note)['text'] = None
    payload, digest = state.encode(old)
    with net.store.tx() as db:
        db.execute('UPDATE resplit_history SET before_state=?,before_digest=? WHERE id=?', (payload, digest, hid))
    recovered = archive.read(net, slug, hid, scope='project', item=f'note:{note}')
    assert recovered['text'] == '' and recovered['item']['provenance']['text_was_null']
