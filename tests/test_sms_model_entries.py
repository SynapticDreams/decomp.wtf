"""Entry geometry and register/reset facts belong to the selected cartridge model."""
from decompnet.rom import sms, sms_trace
from decompnet.rom.sms_analysis import AnalysisLimits, Budget
from decompnet.rom.sms_mapping import Mapper

from .test_sms import make_rom


def test_offset_zero_running_in_slot_two_does_not_borrow_the_reset_recipe():
    rom = make_rom(size=0x20000, code={0: bytes.fromhex("cd0002 c9"), 0x200: b"\xc9"})
    found = sms_trace.Tracer(rom).follow({0: (0x8000, "sym")})
    assert found.code[0] == 3 and 0x200 in found.starts
    assert all(state.registers == (None, None, None) and state.control_bits(3) is None
               for state in found.entered[0x200])


def test_a_symbol_at_cpu_zero_is_not_a_power_on_reset_event():
    rom = make_rom(size=0x20000, code={0: bytes.fromhex("cd0040 c9"), 0x4000: b"\xc9"})
    found = sms_trace.Tracer(rom).follow({0: (0, "sym")})
    assert 0x4000 not in found.starts
    assert 0x4000 in sms_trace.Tracer(rom).follow({0: (0, "vector")}).starts


def test_mapperless_reset_does_not_invent_sega_control_or_raw_selector_latches():
    state = Mapper("mapperless", 0xC000).reset()
    assert state.registers == (None, None, None) and state.control is None


def test_mapperless_entry_and_budget_qualification_retain_only_its_fixed_wiring():
    rom = make_rom(size=0xC000, code={0: b"\xc9"})
    model = Mapper("mapperless", len(rom))
    entry = model.entry(0, 0)
    assert entry.banks == (0, 1, 2) and entry.registers == (None, None, None) and entry.control is None
    budget = Budget(AnalysisLimits(rounds=1))
    found = sms_trace.Tracer(rom, mapper="mapperless", budget=budget).follow({0: (0, "vector")})
    assert found.exhausted
    assert all(state == entry for state in found.entered[0])
    assert model.resolve(0x8123, entry).rom_offset == 0x8123


def test_selected_register_api_never_turns_entry_geometry_into_raw_latches():
    model = Mapper("sega", 0x20000)
    entry = model.entry(0x14000, 0x8000)
    assert model.register_slot(0xFFFF) == 2 and model.is_mapper_register(0xFFFC)
    assert model.resolve(0x8000, model.write(entry, 0xFFFF, 6)).rom_offset is None  # shift bits remain unknown
    flat = Mapper("mapperless", 0xC000)
    assert flat.register_slot(0xFFFF) is None and not flat.is_mapper_register(0xFFFC)
    assert flat.write(flat.entry(0, 0), 0xFFFF, 6) == flat.entry(0, 0)


def test_matching_entry_correction_does_not_hide_the_actual_reset_root():
    rom = make_rom(size=0x20000, code={
        0: bytes.fromhex("cd0040 18fe"), 0x4000: b"\xc9",
        **{at: b"\xc9" for at in sms.VECTORS if at},
    })
    assert 0x4000 in sms.candidates(rom, hints={"entries": {0: 0}})[0]
