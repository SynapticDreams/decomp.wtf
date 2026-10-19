"""Byte-pattern suggestions are bounded, revision checked and never select a profile."""
from decompnet.app.engine import RomNetwork
from decompnet.rom import sms_mapper_evidence

from .test_sms import make_rom


def test_conflicting_byte_patterns_and_small_size_remain_low_confidence():
    report = sms_mapper_evidence.inspect(bytes.fromhex('320000 32ffff') + b'\x00' * 100)
    assert {c['mapper'] for c in report['candidates']} == {'codemasters', 'sega', 'mapperless'}
    assert report['ambiguous'] and report['requires_declaration'] and report['confidence'] == 'low'
    assert report['evidence'] == [
        {'offset': 0, 'address': 0, 'mapper': 'codemasters', 'kind': 'byte-pattern'},
        {'offset': 3, 'address': 0xFFFF, 'mapper': 'sega', 'kind': 'byte-pattern'}]
    assert all(c['confidence'] == 'low' for c in report['candidates'])


def test_scan_and_records_are_bounded_without_hiding_truncation():
    report = sms_mapper_evidence.inspect(bytes.fromhex('320080') * 40000)
    assert report['scan_bytes'] == 0x10000 and report['scan_truncated']
    assert len(report['evidence']) == report['record_limit'] == 32
    assert report['records_truncated'] and report['pattern_count'] > 32
    assert sms_mapper_evidence.inspect(b'\x00' * 0x20000)['candidates'] == []


def test_project_inspection_keeps_profile_unresolved_and_rejects_changed_input(tmp_path):
    net = RomNetwork(tmp_path / 'state.db', tmp_path / 'projects')
    net.auto_install_tools = False
    slug = net.import_rom(make_rom(code={0: bytes.fromhex('320080 18fe')}),
                          name='fixture.sms', confirmed=True, log=lambda *_: None)
    proj = net.project_row(slug)
    before = net.cfg(proj)
    report = net.sms.inspect(slug)
    assert report['profile']['mapper'] == 'unknown' and not report['supported']
    assert report['suggestions']['available'] and net.cfg(proj) == before
    from pathlib import Path
    path = Path(proj['root']) / before['rom']['file']
    path.write_bytes(path.read_bytes()[:-1] + b'\x80')
    assert not net.sms.inspect(slug)['suggestions']['available']
    assert net.cfg(proj) == before
