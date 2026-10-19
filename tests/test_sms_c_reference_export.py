"""Stored C references retain their actual named-unit context without claiming linked replacement."""
import hashlib
import json
from pathlib import Path

import pytest

from decompnet.rom import gb_build, sms_asm

from .test_sms_profile_migration import project as fixture_project, function
from .test_sms_resplit_source_check import C

project = fixture_project


@pytest.mark.skipif(not gb_build.available('z80') or not sms_asm.available(), reason='needs pinned GBDK and WLA-DX')
def test_named_unit_c_reference_keeps_its_header_flags_and_truthful_scope(project):
    net, slug = project
    fn = function(net, slug)
    unit, header = '../authored/unit', '#define AUTHORED_VALUE 7\n'
    flags = ['--fsigned-char', '--opt-code-size']
    net._update_cfg(slug, lambda cfg: cfg['compiler'].update(units={unit: {'flags': flags}}))
    with net.store.tx() as db:
        db.execute('UPDATE functions SET unit=? WHERE id=?', (unit, fn['id']))
        db.execute('UPDATE context_versions SET header=? WHERE project_id=?', ('#define AUTHORED_VALUE 99\n', fn['project_id']))
        db.execute('INSERT INTO context_versions(project_id,version,unit,header) VALUES(?,500,?,?)', (fn['project_id'], unit, header))
    agent, _ = net.local_agent('authored_reference_writer')
    source = C.replace('return 7', 'return AUTHORED_VALUE')
    assert net.attempt(agent, fn['name'], source, slug)['matched']
    result = net.export_rom(slug)
    assert result['identical'], result['log']
    out = Path(result['path'])
    record, = json.loads((out / 'c' / 'references.json').read_text())['references']
    assert record['unit'] == unit and record['context_unit'] == unit and record['context_version'] == 500
    assert record['compiler_context_at_export']['flags'] == flags
    assert not record['verified_by_export'] and not record['source_linked']
    assert record['acceptance_context'] == 'not_attested'
    emitted = out / record['file']
    assert emitted.resolve().is_relative_to((out / 'c').resolve())
    assert emitted.parent.name.startswith('unit_') and emitted.parent.joinpath('context.h').read_text() == header
    assert record['context_sha256'] == hashlib.sha256(header.encode()).hexdigest()
    assert 'This export does not compile or link' in emitted.read_text()
    compiled = gb_build.compile_function(emitted.read_text(), fn['name'], arch='z80', context_header=header, opt=flags)
    assert compiled.code == bytes(fn['target'])  # This fixture's reference is usable; the build does not link it.
