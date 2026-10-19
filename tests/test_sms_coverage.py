"""Authored SMS ROM traces: coordinate validation, sequential entries and observed CPU windows."""
from dataclasses import replace

import pytest

from decompnet.rom import sms, sms_coverage
from decompnet.rom.coverage import CoverageError
from decompnet.rom.sms_mapping import BusState, Mapper

from .test_sms import make_rom


def image(code=None, size=0x20000):
    return make_rom(size=size, code={0: bytes.fromhex("18fe"), **(code or {})})


def read(text, rom=None, mapper="sega"):
    return sms_coverage.read_trace(text, rom or image(), mapper=mapper)


def test_sequential_calls_record_each_observed_bank_instead_of_a_unique_address_guess():
    rom = image({0x100: bytes.fromhex("cd0080"), 0x103: bytes.fromhex("cd0080"),
                 0x14000: bytes.fromhex("3e05c9"), 0x18000: bytes.fromhex("3e06c9")})
    cov = read("00:0100\n05:8000\n05:8002\n00:0103\n06:8000\n", rom)
    assert cov.entries == {0x14000, 0x18000}
    assert cov.code[0x100:0x103] == b"\x01" * 3
    assert cov.cpus[0x14000] == {0x8000} and cov.cpus[0x18000] == {0x8000}


@pytest.mark.parametrize("gap", ["00:0103", "missing records", "00:c000", "05:0123"])
def test_unrelated_target_occurrences_and_gaps_do_not_prove_a_call_entry(gap):
    rom = image({0x100: bytes.fromhex("cd0080"), 0x103: bytes.fromhex("c9"), 0x14000: b"\xc9"})
    cov = read(f"00:0100\n{gap}\n05:8000\n", rom)
    assert not cov.entries
    assert cov.code[0x14000]


def test_known_same_window_mapping_cannot_jump_to_another_bank_without_an_intervening_event():
    rom = image({0x14100: bytes.fromhex("cd0080"), 0x18000: b"\xc9"})
    cov = read("05:8100\n06:8000\n", rom)
    assert not cov.entries and cov.code[0x18000]


def test_comments_preserve_sequence_and_conditional_call_fallthrough_is_not_an_entry():
    rom = image({0x100: bytes.fromhex("cc0080"), 0x103: b"\xc9", 0x14000: b"\xc9"})
    assert read("00:0100\n; annotation\n05:8000\n", rom).entries == {0x14000}
    assert not read("00:0100\n00:0103\n05:8000\n", rom).entries


def test_rst_observations_establish_fixed_prefix_entries():
    cov = read("05:8100\n00:0028\n", image({0x14100: bytes.fromhex("ef"), 0x28: b"\xc9"}))
    assert cov.entries == {0x28}


@pytest.mark.parametrize("coordinate", ["05:0123", "00:c000", "00:ffff", "fff:8000", "09:4000"])
def test_invalid_rom_coordinates_are_rejected_instead_of_reattributed(coordinate):
    with pytest.raises(CoverageError, match="no valid cartridge-ROM"):
        read(coordinate)


def test_explicit_non_rom_sources_never_acquire_a_cartridge_offset():
    model = Mapper("sega", 0x20000)
    state = BusState.cartridge_only((0, 1, 5))
    for context in (replace(state, control=8), replace(state, bios=True), replace(state, cartridge=False), BusState()):
        assert sms_coverage.trace_address(model, 5, 0x8123, context).rom_offset is None
    assert sms_coverage.trace_address(model, 5, 0x8123, state).rom_offset == 0x14123


def test_instruction_fetch_does_not_mark_an_unestablished_window_across_a_boundary():
    rom = image({0x17FFF: bytes.fromhex("cd"), 0x18000: bytes.fromhex("0080")})
    cov = read("05:bfff", rom)
    assert cov.code[0x17FFF] and not cov.code[0x18000] and not cov.entries


def test_slot_zero_trace_cpu_is_retained_when_seeding_discovery():
    rom = image({0x11000: bytes.fromhex("3e04c9")})
    cov = read("04:1000\n04:1002", rom)
    assert cov.cpus[0x11000] == {0x1000}
    starts, _ = sms.candidates(rom, hints={"coverage": cov})
    assert starts[0x11000] == (0x1000, "ran")


def test_multiple_observed_cpu_windows_do_not_choose_one_arbitrarily():
    rom = image({0x14000: bytes.fromhex("3e05c9")})
    cov = read("05:4000\n05:8000", rom)
    assert cov.cpus[0x14000] == {0x4000, 0x8000}
    starts, _ = sms.candidates(rom, hints={"coverage": cov})
    assert 0x14000 not in starts


def test_mapperless_coordinates_must_match_flat_wiring():
    cov = read("02:8100", image(size=0xC000), mapper="mapperless")
    assert cov.code[0x8100]
    with pytest.raises(CoverageError, match="no valid cartridge-ROM"):
        read("01:8100", image(size=0xC000), mapper="mapperless")


@pytest.mark.parametrize("mapper", ["unknown", "unsupported"])
def test_unqualified_models_are_not_silently_interpreted_as_sega(mapper):
    with pytest.raises(CoverageError, match="declared supported model"):
        read("00:0100", mapper=mapper)
