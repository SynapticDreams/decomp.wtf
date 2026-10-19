"""A ROM entry cannot invent raw latches/shift bits; joins retain only shared control-bit facts."""
from decompnet.rom.sms_mapping import BusState, Mapper, entry_state, join


def test_entry_geometry_does_not_invent_control_or_raw_registers():
    model = Mapper("sega", 0x80000)
    state = entry_state(0x14123, 0x8123, model.size)
    assert state.banks == (None, None, 5) and state.registers == (None,) * 3
    assert state.control_known == 8 and state.control_flag(8) is False
    assert state.control_bits(3) is None and state.control_flag(0x80) is None
    assert model.resolve(0x8124, state).rom_offset == 0x14124
    # Writing 5 need not select 5 when shift bits are unestablished.
    written = model.write(state, 0xFFFF, 5)
    assert model.resolve(0x8000, written).rom_offset is None
    initialized = model.write(model.write(written, 0xFFFC, 0), 0xFFFF, 5)
    assert model.resolve(0x8000, initialized).rom_offset == 0x14000


def test_join_keeps_agreed_rom_ram_and_shift_bits_when_an_unrelated_bit_differs():
    model = Mapper("sega", 0x80000)
    base = model.reset()
    mixed = join([base, model.write(base, 0xFFFC, 4)])
    assert mixed.control_bits(255) is None and mixed.control_bits(4) is None
    assert mixed.control_flag(8) is False and mixed.control_flag(0x10) is False
    assert mixed.control_bits(3) == 0
    assert model.resolve(0x8000, model.write(mixed, 0xFFFF, 5)).rom_offset == 0x14000
    assert model.resolve(0xC000, mixed).space == "wram"


def test_joined_ram_selection_does_not_invent_a_ram_bank():
    model = Mapper("sega", 0x80000)
    base = model.reset()
    mixed = join([model.write(base, 0xFFFC, 8), model.write(base, 0xFFFC, 12)])
    selected = model.resolve(0x8000, mixed)
    assert selected.space == "cart_ram" and selected.bank is None and selected.rom_offset is None


def test_partial_control_values_are_canonical_and_do_not_gain_unknown_bits():
    state = BusState.cartridge_only(control=255, control_known=8)
    assert state.control == 8 and state.control_bits(8) == 8 and state.control_bits(0x80) is None
    assert join([state, state]) == state
    assert BusState.cartridge_only(control=0, control_known=0).control is None
    assert BusState.cartridge_only(control=None).control_known == 0


def test_an_isolated_fixed_prefix_entry_does_not_establish_page_zero_or_ram_selection():
    model = Mapper("sega", 0x80000)
    state = entry_state(0x123, 0x123, model.size)
    assert state.control_known == 0 and state.registers == (None,) * 3
    assert model.resolve(0x123, state).rom_offset == 0x123
    assert model.resolve(0x1234, state).space == "unknown"
    assert model.resolve(0xC123, state).space == "unknown"
