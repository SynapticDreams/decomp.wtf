"""Selected-model names distinguish selector writes, ROM reads and ordinary RAM."""
from dataclasses import replace

import pytest

from decompnet.rom import sms_asm, sms_hw


def routine(code, mapper='codemasters'):
    return sms_asm.Routine('SelectHandler', 0, 0x200, bytes.fromhex(code),
                           {'SelectHandler': 0x200}, {0x200: 'SelectHandler'}, {0x200: 0x200}, mapper=mapper)


def test_drafts_use_write_only_codemasters_selectors_and_keep_mapperless_ram_separate():
    write = routine('3e03 320080 c9')
    assert 'ld (CodemastersSlot2), a' in sms_asm.draft(write)
    read = routine('3a0080 c9')
    assert 'CodemastersSlot' not in sms_asm.draft(read)
    assert 'ld a, ($8000)' in sms_asm.draft(read)
    mapperless = replace(routine('3affff c9'), mapper='mapperless', banks=3, rom_size=0xC000)
    assert 'MapperSlot' not in sms_asm.draft(mapperless)
    assert sms_hw.names()['MapperSlot2'] == 0xFFFF  # retained stored-source aliases
    assert sms_hw.names()['CodemastersSlot0'] == 0


@pytest.mark.skipif(not sms_asm.available(), reason='needs WLA-DX')
def test_judge_moves_codemasters_hardware_names_and_rejects_numeric_selector():
    r = routine('3e03 320080 c9')
    header = ('; Selects the authored handler bank without changing other selectors.\n'
              '; Input: none. Output: A holds the bank, flags preserved.\n')
    text = header + 'SelectHandler:\n    ld a, 3\n    ld (CodemastersSlot2), a\n    ret\n'
    verdict = sms_asm.judge(r, text)
    assert verdict.ok, verdict.problems
    numeric = sms_asm.judge(r, text.replace('CodemastersSlot2', '$8000'))
    assert not numeric.ok and any('hardware' in p for p in numeric.problems)


@pytest.mark.skipif(not sms_asm.available(), reason='needs WLA-DX')
@pytest.mark.parametrize('name,define', [('UpperByte', '.DEFINE UpperByte $FFFF\n'), ('MapperSlot2', '')])
def test_non_sega_top_ram_names_and_legacy_aliases_remain_acceptable(name, define):
    r = replace(routine('3affff c9'), mapper='mapperless', banks=3, rom_size=0xC000)
    text = ('; Reads the authored work RAM byte and returns its value in A.\n'
            '; Input: none. Output: A contains the RAM byte, flags preserved.\n' + define +
            f'SelectHandler:\n    ld a, ({name})\n    ret\n')
    verdict = sms_asm.judge(r, text)
    assert verdict.ok, verdict.problems
