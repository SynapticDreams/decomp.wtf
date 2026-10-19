"""Declared WLA coordinates preserve records without guessing code or semantic names."""
import copy
import hashlib
import zlib

import pytest

from decompnet.rom import wla_layout, wla_symbols
from .sms_wla_fixture import layout_for

IMAGE = b'\xff' * 0xC000


def normalized(text, declaration=None):
    return wla_symbols.normalize(wla_symbols.read(text.encode()),
                                 wla_layout.declare(declaration or layout_for(IMAGE), IMAGE), IMAGE)


def test_nonuniform_banks_aliases_duplicate_cpu_windows_and_automatic_seeds_are_distinct():
    text = '[labels]\n01:2100 First\n01:2100 Alias\n00:1100 Main\n02:1100 Paged\n01:2300 _LABEL_2300_\n'
    result = normalized(text)
    assert result.names == {(0, 0x2100): 'First', (0, 0x1100): 'Main', (2, 0x1100): 'Paged'}
    assert result.seeds[(0, 0x2300)] == '_LABEL_2300_'
    assert (0, 0x2300) not in result.names
    assert result.aliases[(0, 0x2100)] == ['First', 'Alias']
    assert [r['rom_offset'] for r in result.records] == [0x2100, 0x2100, 0x1100, 0x9100, 0x2300]
    assert result.document.raw == text.encode()
    assert result.document.sha256 == hashlib.sha256(text.encode()).hexdigest()
    report = result.report()
    assert report['source']['sha256'] == result.document.sha256
    assert report['records'][0]['bank'] == 1 and report['records'][0]['coordinates'][0]['physical_bank'] == 0
    assert 'raw' not in report and 'scope' in report


def test_data_ram_locals_unknown_and_impossible_fixed_prefix_do_not_seed_code():
    result = normalized('[labels]\n01:2200 Table\n00:c000 wState\n01:2400 Unknown\n'
                        '01:2100 _DATA_2100_\n01:2103 @local\n02:0100 WrongPrefix\n01:2106 Owner.child\n'
                        '01:2203 _LABEL_2203_\n')
    assert not result.names and not result.seeds
    assert [r['status'] for r in result.records] == ['data', 'ram', 'suggestion', 'data', 'local', 'unresolved', 'local', 'data']
    assert result.records[5]['rom_offset'] == 0x8100  # preserve rejected physical correspondence for inspection


@pytest.mark.parametrize('change,expected', [('view', 'ambiguous_view'), ('name', 'conflicting_name'),
                                            ('role', 'conflicting_role'), ('cpu', 'ambiguous_cpu_entry')])
def test_ambiguity_and_conflicting_names_or_roles_remain_suggestions(change, expected):
    layout = layout_for(IMAGE)
    text = '[labels]\n01:2100 First\n'
    if change == 'view':
        layout['slots'].append({'id': 5, 'start': 0x2000, 'size': 0x4000, 'space': 'rom'})
        layout['views'].append({'bank': 1, 'slot': 5, 'offset': 0, 'size': 0x200, 'role': 'data'})
    elif change == 'name':
        text += '02:8100 First\n'
    elif change == 'role':
        text += '01:2100 _DATA_2100_\n'
    else:
        text = '[labels]\n02:8100 Third\n02:0100 Other\n'
        # Use a flat offset above Sega's fixed prefix so both declared CPU coordinates are valid.
        text = text.replace('8100', '9000').replace('0100', '1000')
        layout['views'][5]['size'] = 0x1200
    result = normalized(text, layout)
    assert not result.names and not result.seeds
    assert {r['status'] for r in result.records} == {expected}


def test_parser_respects_sections_comments_and_preserves_original_source_bytes():
    raw = b'\xef\xbb\xbf; arbitrary private comment\r\n[information]\r\nversion 3\r\nwlasymbol true\r\n[labels]\r\n01:2100 First ; comment\r\n[definitions]\r\n01:2200 NotALabel\r\n[future section]\r\n02:8100 AlsoNotALabel\r\n'
    document = wla_symbols.read(raw)
    assert document.raw == raw and document.version == 3
    assert document.records == [{'line': 6, 'bank': 1, 'cpu': 0x2100, 'name': 'First'}]
    result = wla_symbols.normalize(document, wla_layout.declare(layout_for(IMAGE), IMAGE), IMAGE)
    assert result.names == {(0, 0x2100): 'First'}
    assert 'private' not in str(result.report())


def test_unknown_symbol_version_retains_records_without_applying_them():
    result = normalized('[information]\nversion 4\n[labels]\n01:2100 First\n')
    assert result.records[0]['status'] == 'unsupported_symbol_version'
    assert result.document.version == 4 and not result.names and not result.seeds


def test_rom_checksum_is_verified_as_input_correspondence():
    text = f'[labels]\n01:2100 First\n[rom checksum]\n{zlib.crc32(IMAGE):08x}\n'
    assert normalized(text).names == {(0, 0x2100): 'First'}
    with pytest.raises(ValueError, match='checksum differs'):
        normalized(text.replace(f'{zlib.crc32(IMAGE):08x}', '00000000'))


@pytest.mark.parametrize('text', ['[information]\nversion x', '[information]\nversion 1\nversion 2',
                                 '[rom checksum]\nno checksum', '[rom checksum]\n00000000\n00000000'])
def test_malformed_identity_or_format_metadata_is_refused(text):
    with pytest.raises(ValueError):
        wla_symbols.read(text.encode())


def test_parser_and_normalizer_budgets_fail_explicitly(monkeypatch):
    with pytest.raises(ValueError, match='8 MiB'):
        wla_symbols.read(b'x' * (wla_symbols.MAX_BYTES + 1))
    monkeypatch.setattr(wla_symbols, 'MAX_LINES', 1)
    with pytest.raises(ValueError, match='line budget'):
        wla_symbols.read(b'\n\n')
    monkeypatch.setattr(wla_symbols, 'MAX_LINES', 100)
    monkeypatch.setattr(wla_symbols, 'MAX_RECORDS', 1)
    with pytest.raises(ValueError, match='record budget'):
        wla_symbols.read(b'01:2100 First\n01:2101 Second\n')
    monkeypatch.setattr(wla_symbols, 'MAX_VIEW_CHECKS', 0)
    with pytest.raises(ValueError, match='view-check budget'):
        normalized('01:2100 First\n')
    monkeypatch.setattr(wla_symbols, 'MAX_VIEW_CHECKS', 100)
    monkeypatch.setattr(wla_symbols, 'MAX_COORDINATES', 0)
    with pytest.raises(ValueError, match='coordinate budget'):
        normalized('01:2100 First\n')


def test_normalizing_against_changed_input_is_refused():
    layout = wla_layout.declare(layout_for(IMAGE), IMAGE)
    changed = bytearray(IMAGE); changed[0] ^= 1
    with pytest.raises(ValueError, match='different normalized input'):
        wla_symbols.normalize(wla_symbols.read(b'01:2100 First'), layout, bytes(changed))


def test_caller_changes_cannot_mutate_validated_geometry():
    declaration = layout_for(IMAGE)
    original = copy.deepcopy(declaration)
    layout = wla_layout.declare(declaration, IMAGE)
    declaration['banks'][1]['offset'] = 0
    declaration['views'][1]['role'] = 'data'
    assert layout.declaration == original
    assert layout.coordinates(1, 0x2100)[0]['rom_offset'] == 0x2100


def test_declared_ram_in_a_low_cpu_window_never_becomes_a_cartridge_offset():
    value = layout_for(IMAGE)
    value['slots'][1]['space'] = 'ram'
    result = normalized('01:2100 Buffer\n01:2300 _LABEL_2300_\n', value)
    assert not result.names and not result.seeds
    assert all(r['status'] == 'ram' and r['rom_offset'] is None for r in result.records)


def test_many_alias_records_are_preserved_in_source_order_without_duplicate_effective_names():
    names = [f'Alias_{n}' for n in range(3000)]
    text = '\n'.join(f'01:2100 {name}' for name in [*names, names[0]])
    result = normalized(text)
    assert len(result.records) == 3001
    assert result.aliases[(0, 0x2100)] == names
    assert result.names == {(0, 0x2100): names[0]} and len(result.seeds) == 1


def test_public_reader_requires_geometry_or_explicit_physical_code_coordinates():
    text = '01:2100 First\n01:2100 Alias\n'
    with pytest.raises(ValueError, match='need layout/image'):
        wla_symbols.read_names(text)
    assert wla_symbols.read_names(text, layout=layout_for(IMAGE), image=IMAGE) == {(0, 0x2100): 'First'}
    assert wla_symbols.read_names(text, physical=True) == {(1, 0x2100): 'Alias'}
    with pytest.raises(ValueError, match='choose declared'):
        wla_symbols.read_names(text, layout=layout_for(IMAGE), image=IMAGE, physical=True)
