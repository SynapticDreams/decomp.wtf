"""Invalid assembler geometry cannot reattribute bytes or turn unknown sources into ROM."""
import pytest

from decompnet.rom import wla_layout
from .sms_wla_fixture import layout_for

IMAGE = b'\xff' * 0xC000


@pytest.mark.parametrize('change', ['version', 'identity', 'gap', 'overlap', 'duplicate_bank', 'missing_bank',
                                    'bank_end', 'duplicate_slot', 'slot_end', 'missing_slot', 'view_end',
                                    'role', 'space', 'boolean', 'extra_field', 'bank_budget', 'view_budget'])
def test_invalid_revision_or_geometry_is_refused_before_any_coordinates_are_used(change, monkeypatch):
    value = layout_for(IMAGE)
    if change == 'version': value['version'] = 2
    elif change == 'identity': value['input']['sha256'] = '0' * 64
    elif change == 'gap': value['banks'][1]['offset'] += 1
    elif change == 'overlap': value['banks'][1]['offset'] -= 1
    elif change == 'duplicate_bank': value['banks'][1]['id'] = 0
    elif change == 'missing_bank': value['banks'].pop()
    elif change == 'bank_end': value['banks'][-1]['size'] += 1
    elif change == 'duplicate_slot': value['slots'][1]['id'] = 0
    elif change == 'slot_end': value['slots'][-1].update(start=65535, size=2)
    elif change == 'missing_slot': value['views'][1]['slot'] = 255
    elif change == 'view_end': value['views'][1]['size'] = 0x6001
    elif change == 'role': value['views'][1]['role'] = 'function'
    elif change == 'space': value['slots'][0]['space'] = 'cartridge'
    elif change == 'boolean': value['views'][1]['bank'] = True
    elif change == 'extra_field': value['views'][1]['bank_offset'] = 0
    elif change == 'bank_budget': monkeypatch.setattr(wla_layout, 'MAX_BANKS', 1)
    else: monkeypatch.setattr(wla_layout, 'MAX_VIEWS', 1)
    with pytest.raises(ValueError):
        wla_layout.declare(value, IMAGE)


def test_nonstandard_slot_ids_and_ram_bank_namespace_do_not_imply_physical_rom_banks():
    value = layout_for(IMAGE)
    value['views'][-1]['bank'] = 200
    layout = wla_layout.declare(value, IMAGE)
    assert layout.coordinates(200, 0xC100)[0]['space'] == 'ram'
    assert layout.coordinates(200, 0xC100)[0]['rom_offset'] is None
    assert not layout.coordinates(200, 0x2100)
    assert layout.coordinates(1, 0x2100)[0]['physical_bank'] == 0


def test_shared_hardware_model_refuses_mapperless_paging_and_sega_fixed_prefix_contradictions():
    sega = wla_layout.declare(layout_for(IMAGE), IMAGE)
    assert sega.coordinates(2, 0x0100)[0]['space'] == 'unresolved'
    assert sega.coordinates(2, 0x1000)[0]['rom_offset'] == 0x9000
    flat = wla_layout.declare(layout_for(IMAGE), IMAGE, mapper='mapperless')
    assert flat.coordinates(2, 0x1000)[0]['space'] == 'unresolved'
    assert flat.coordinates(2, 0x8100)[0]['rom_offset'] == 0x8100


def test_unknown_device_slot_remains_inspectable_without_becoming_cartridge_rom():
    value = layout_for(IMAGE)
    value['slots'][1]['space'] = 'unknown'
    layout = wla_layout.declare(value, IMAGE)
    row = layout.coordinates(1, 0x2100)[0]
    assert row['space'] == 'unknown' and row['rom_offset'] is None
