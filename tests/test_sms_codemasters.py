"""Authored Codemasters cases qualify shared selectors and expose disputed wiring."""
from dataclasses import replace

import pytest

from decompnet.rom import sms_coverage, sms_trace
from decompnet.rom.sms_mapping import BusState, Mapper, join, rom_coordinate

from .test_sms import make_rom

SIZE = 0x20000


@pytest.mark.parametrize('cpu,slot', [(0, 0), (0x4000, 1), (0x8000, 2)])
def test_canonical_selectors_page_the_whole_window_without_ram_readback(cpu, slot):
    model = Mapper('codemasters', SIZE)
    state = model.write(model.reset(), cpu, 0x85)
    assert state.banks[slot] == 5 and state.registers[slot] == 0x85
    assert model.resolve(cpu + 0x123, state).rom_offset == 0x14123
    assert model.resolve(cpu, state).space == 'rom'
    assert model.register_slot(cpu) == slot and model.is_mapper_register(cpu)
    assert model.write(state, 0xFFFF, 3) == state
    assert model.resolve(0xFFFF, state).space == 'wram'


def test_reset_and_entry_keep_effective_selection_separate_from_raw_registers():
    model = Mapper('codemasters', SIZE)
    reset = model.reset()
    assert reset.banks == reset.registers == (0, 1, 0)
    assert model.resolve(0x8000, reset).rom_offset == 0
    for cpu in (0x123, 0x8123, 0xA123):
        flat = 0x14000 + (cpu & 0x3FFF)
        state = model.entry(flat, cpu)
        assert state.banks[cpu // 0x4000] == 5 and state.registers == (None,) * 3
        assert model.resolve(cpu, state).rom_offset == flat
        assert state.control_flag(0x80) is (False if cpu >= 0xA000 else None)
        assert rom_coordinate(model, 5, cpu).rom_offset == flat
    assert model.resolve(0x123, BusState.cartridge_only(control=None)).space == 'unknown'
    assert sms_trace.resolve(0x123, 0x14100, 0x100, 1, 0, SIZE, mapper='codemasters') == 0x14123


def test_ram_flag_does_not_invent_ram_presence_or_expose_original_rom_as_ram():
    model = Mapper('codemasters', SIZE)
    state = model.write(model.write(model.reset(), 0x8000, 5), 0x4000, 0x81)
    assert state.registers[1] == 0x81 and state.banks[1] == 1
    assert model.resolve(0x8123, state).rom_offset == 0x14123
    assert model.resolve(0xA123, state).space == 'unknown'
    assert model.resolve(0xC123, state).space == 'wram'
    assert model.resolve(0xA123, replace(state, control=0x80, control_known=0x80)).space == 'cart_ram'
    restored = model.write(state, 0x4000, 1)
    assert model.resolve(0xA123, restored).rom_offset == 0x16123
    assert model.resolve(0xA123, join([state, restored])).space == 'unknown'
    unknown = model.unknown_write(restored)
    assert unknown.banks == unknown.registers == (None,) * 3
    assert not unknown.rom_modified


@pytest.mark.parametrize('cpu,slot', [(0x123, 0), (0x4123, 1), (0xA123, 2)])
def test_disputed_mirrors_invalidate_affected_selector_without_guessing_a_decode(cpu, slot):
    model = Mapper('codemasters', SIZE)
    state = model.write(model.reset(), cpu, 5)
    assert state.banks[slot] is None and state.registers[slot] is None
    assert all(state.banks[k] == model.reset().banks[k] for k in range(3) if k != slot)
    if slot == 1:
        assert model.resolve(0xA000, state).space == 'unknown'


@pytest.mark.parametrize('size', [0x4000, 0xC000, 0x100000])
def test_unqualified_sizes_are_rejected(size):
    with pytest.raises(ValueError, match='32 to 512 KiB'):
        Mapper('codemasters', size)


def follow(code):
    return sms_trace.Tracer(make_rom(size=SIZE, code=code), mapper='codemasters').follow({0: (0, 'vector')})


def test_slot_zero_self_paging_fetches_next_instruction_and_vectors_from_new_bank():
    found = follow({0: bytes.fromhex('3e04 320000 cd0002 18fe'),
                    0x10005: bytes.fromhex('cd0001 18fe'), 0x10100: b'\xc9', 0x200: b'\xc9'})
    assert found.starts[0x10100] == (0x100, 'call')
    assert 0x200 not in found.starts and 0x10005 in found.code and 5 not in found.code
    assert all(state.banks[0] == 4 for state in found.entered[0x10100])


def test_ram_ambiguity_and_noncanonical_writes_are_visible_analysis_limits():
    found = follow({0: bytes.fromhex('3e05 320080 3e81 320040 cd0080 18fe'),
                    0x14000: bytes.fromhex('cd00a0 c9'), 0x16000: b'\xc9'})
    assert 0x14000 in found.starts and 0x16000 not in found.starts
    assert any('RAM wiring' in reason for reason in found.unresolved[0])
    mirrored = follow({0: bytes.fromhex('3e05 320100 cd0002 18fe'), 0x200: b'\xc9'})
    assert 0x200 not in mirrored.starts
    assert any('mirror decoding' in reason for reason in mirrored.unresolved[0])


def test_divergent_callers_do_not_choose_one_slot_two_bank_for_shared_callee():
    found = follow({0: bytes.fromhex('280a 3e05 320080 cd0002 18fe 3e06 320080 cd0002 18fe'),
                    0x200: bytes.fromhex('cd0080 c9'), 0x14000: b'\xc9', 0x18000: b'\xc9'})
    assert {s.banks[2] for s in found.entered[0x200]} == {5, 6}
    assert found.unresolved[0x200]


def test_rom_trace_coordinates_include_paged_prefix_without_inventing_other_windows():
    image = make_rom(size=SIZE, code={0x14020: bytes.fromhex('cd3000'), 0x14030: b'\xc9'})
    cov = sms_coverage.read_trace('05:0020\n05:0030\n', image, mapper='codemasters')
    assert cov.entries == {0x14030} and cov.cpus[0x14030] == {0x30}
    assert cov.code[0x14020:0x14023] == b'\x01' * 3
