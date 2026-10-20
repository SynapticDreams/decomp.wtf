"""The Korean board (rom/sms_mapping.py): slots 0 and 1 wired to banks 0 and 1, slot 2 selected by a write to exactly
$A000, reset to bank 2, and no Sega registers (MAME sega8_korean_device, Gearsystem KoreanMemoryRule)."""

from __future__ import annotations

import pytest

from decompnet.rom import sms, sms_hw, sms_mapper_evidence, sms_profile, sms_trace
from decompnet.rom.sms_mapping import BusState, Mapper

from .test_sms import make_rom

SIZE = 0x20000
KOREAN = Mapper("korean", SIZE)


def test_slots_zero_and_one_are_wired_and_slot_two_follows_a000():
    state = KOREAN.reset()
    assert [KOREAN.resolve(cpu, state).rom_offset for cpu in (0x0123, 0x4123, 0x8123)] == [0x0123, 0x4123, 0x8123]
    state = KOREAN.write(state, 0xA000, 5)
    assert KOREAN.resolve(0x8123, state).rom_offset == 0x14123 and state.registers == (None, None, 5)
    assert KOREAN.resolve(0x0123, BusState.cartridge_only((7, 6, 5))).rom_offset == 0x0123  # (wired, not paged)
    assert KOREAN.write(state, 0xA000, 0x1D).banks[2] == 5  # masked to the image's 8 banks


@pytest.mark.parametrize("cpu", [0xA001, 0x9FFF, 0x8000, 0xFFFF, 0xFFFE, 0xFFFD, 0xFFFC, 0x0000, 0x4000])
def test_no_other_address_selects_a_bank(cpu):
    state = KOREAN.write(KOREAN.reset(), cpu, 5)
    assert state == KOREAN.reset() and KOREAN.register_slot(cpu) is None and not KOREAN.is_mapper_register(cpu)
    assert KOREAN.register_slot(0xA000) == 2 and KOREAN.is_mapper_register(0xA000)


def test_unknown_values_and_stores_lose_only_slot_two():
    assert KOREAN.write(KOREAN.reset(), 0xA000, None).banks == (0, 1, None)
    state = KOREAN.unknown_write(KOREAN.write(KOREAN.reset(), 0xA000, 5))
    assert state.banks == (0, 1, None) and KOREAN.resolve(0x4000, state).rom_offset == 0x4000
    assert KOREAN.resolve(0x8000, state).rom_offset is None
    assert KOREAN.write(BusState(), 0xA000, 5).banks[2] is None  # (cartridge selection unresolved)


def test_entry_geometry_establishes_only_slot_two():
    assert KOREAN.entry(0x14010, 0x8010).banks == (0, 1, 5)
    assert KOREAN.entry(0x14010, 0x4010).banks == (0, 1, None)
    assert KOREAN.resolve(0xC123, KOREAN.reset()).space == "wram"  # (no cartridge RAM in this model)


@pytest.mark.parametrize("size", [0x4000, 0x18000, 0x28000])
def test_only_power_of_two_images_of_at_least_32_kib_qualify(size):
    with pytest.raises(ValueError, match="Korean"):
        Mapper("korean", size)


def _found(code: dict) -> dict:
    vectors = {at: b"\xc9" for at in sms.VECTORS if at}
    rom = make_rom(size=SIZE, code={**vectors, 0x0000: bytes.fromhex("c30001"), **code,
                                    0x14000: bytes.fromhex("3e05c9"), 0x8000: bytes.fromhex("3e02c9")})
    return sms_trace.Tracer(rom, mapper="korean").follow({0: (0, "vector")}).starts


def test_discovery_follows_a000_and_ignores_sega_registers():
    assert _found({0x0100: bytes.fromhex("3e05" "3200a0" "cd0080" "18fe")}).get(0x14000) == (0x8000, "call")
    found = _found({0x0100: bytes.fromhex("3e05" "32ffff" "cd0080" "18fe")})  # ld ($ffff),a is RAM here
    assert found.get(0x8000) == (0x8000, "call") and 0x14000 not in found


def test_the_model_is_declarable_named_and_suggested():
    assert "korean" in sms_profile.SUPPORTED and "korean" in sms_profile.MAPPERS
    assert sms_hw.mapper_names("korean", write=True) == {0xA000: "KoreanSlot2"}
    assert sms_hw.mapper_names("korean", write=False) == {}
    assert ".DEFINE KoreanSlot2 $A000" in sms_hw.inc(mapper="korean")
    report = sms_mapper_evidence.inspect(bytes.fromhex("3e05 3200a0") + bytes(0x20000))
    assert {"mapper": "korean", "confidence": "low"} in report["candidates"]
