"""Known stack hazards and asynchronous boundaries cannot become mapper-preserving contracts."""
from decompnet.rom import sms_trace
import pytest
from decompnet.rom.sms_paths import Limits

from .test_sms import make_rom


def test_call_stack_at_zero_cannot_preserve_the_pre_call_slot_two_bank():
    rom = make_rom(size=0x20000, code={
        0: bytes.fromhex("310000 3e05 32ffff cd0080 18fe"), 0x14000: b"\xc9",
    })
    found = sms_trace.Tracer(rom).follow({0: (0, "vector")})
    assert 0x14000 not in found.starts
    assert found.unresolved[0]


def test_write_through_ram_mirror_cannot_restore_a_stale_saved_accumulator():
    rom = make_rom(size=0x20000, code={
        0: bytes.fromhex("31f0df 3e05 f5 3e06 32efff f1 32ffff cd0080 18fe"),
        0x14000: b"\xc9", 0x18000: b"\xc9",
    })
    found = sms_trace.Tracer(rom).follow({0: (0, "vector")})
    assert 0x14000 not in found.starts
    assert found.unresolved[0]


def test_enabled_interrupts_make_save_change_restore_explicitly_conditional():
    rom = make_rom(size=0x20000, code={
        0: bytes.fromhex("3e05 32ffff 3affff f5 fb 3e06 32ffff f1 32ffff cd0080 18fe"),
        0x38: bytes.fromhex("3e07 32ffff ed4d"), 0x14000: b"\xc9",
    })
    found = sms_trace.Tracer(rom).follow({0: (0, "vector"), 0x38: (0x38, "vector")})
    assert found.unresolved[0]
    assert found.unresolved[0x38]


def test_known_nonaliasing_work_ram_stack_preserves_saved_values_and_mapping():
    rom = make_rom(size=0x20000, code={
        0: bytes.fromhex("31f0df 3e05 f5 cd0002 f1 32ffff cd0080 18fe"),
        0x200: b"\xc9", 0x14000: b"\xc9",
    })
    found = sms_trace.Tracer(rom).follow({0: (0, "vector")})
    assert 0x14000 in found.starts and not found.unresolved


def test_callee_write_to_callers_saved_value_is_unqualified_before_restore():
    rom = make_rom(size=0x20000, code={
        0: bytes.fromhex("31f0df 3e05 f5 cd0002 f1 32ffff cd0080 18fe"),
        0x200: bytes.fromhex("3e06 32efff c9"), 0x14000: b"\xc9",
    })
    found = sms_trace.Tracer(rom).follow({0: (0, "vector")})
    assert 0x14000 not in found.starts
    assert "memory write aliases an active physical stack value" in found.unresolved[0]


def test_call_return_push_does_not_reuse_old_ram_shadow_bytes():
    rom = make_rom(size=0x20000, code={
        0: bytes.fromhex("3100e0 3e05 32ffff cd0002 3affff 32ffff cd0080 18fe"),
        0x200: b"\xc9", 0x14000: b"\xc9",
    })
    found = sms_trace.Tracer(rom).follow({0: (0, "vector")})
    assert 0x14000 not in found.starts


@pytest.mark.parametrize("pointer", ["0080", "01c0", "fdff"])
def test_known_rom_and_mapper_stack_destinations_cannot_select_a_guessed_target(pointer):
    rom = make_rom(size=0x20000, code={
        0: bytes.fromhex("31" + pointer + " 3e05 32ffff cd0080 18fe"), 0x14000: b"\xc9",
    })
    found = sms_trace.Tracer(rom).follow({0: (0, "vector")})
    assert 0x14000 not in found.starts and found.unresolved[0]


def test_mapperless_stack_at_zero_does_not_invent_sega_register_aliases():
    rom = make_rom(size=0xC000, code={0: bytes.fromhex("310000 cd0080 18fe"), 0x8000: b"\xc9"})
    found = sms_trace.Tracer(rom, mapper="mapperless").follow({0: (0, "vector")})
    assert 0x8000 in found.starts and not found.unresolved


def test_halt_cannot_assume_a_mapper_preserving_wake_up():
    rom = make_rom(size=0x20000, code={0: bytes.fromhex("3e05 32ffff 76 cd0080 18fe"), 0x14000: b"\xc9"})
    found = sms_trace.Tracer(rom).follow({0: (0, "vector")})
    assert 0x14000 not in found.starts
    assert "asynchronous interrupt-dependent continuation is unqualified" in found.unresolved[0]


def test_paths_with_different_stack_locations_are_not_collapsed_at_one_call():
    rom = make_rom(size=0x20000, code={
        0: bytes.fromhex("3e05 32ffff 31f0df 2805 310000 1800 cd0080 18fe"), 0x14000: b"\xc9",
    })
    found = sms_trace.Tracer(rom).follow({0: (0, "vector")})
    assert 0x14000 in found.starts  # the valid WRAM-stack branch still reaches its conditional target
    assert "physical stack may access a mapper or unqualified memory source" in found.unresolved[0]


def test_known_stack_computed_call_does_not_push_a_second_return_word():
    rom = make_rom(size=0x20000, code={
        0: bytes.fromhex("31f0df 3e05 32ffff cd0002 cd0080 18fe"),
        0x200: bytes.fromhex("210003 110802 d5 e9 cd0080 c9"),
        0x300: bytes.fromhex("3e06 32ffff c9"), 0x18000: b"\xc9", 0x14000: b"\xc9",
    })
    found = sms_trace.Tracer(rom).follow({0: (0, "vector")})
    assert 0x18000 in found.starts and 0x14000 not in found.starts
    assert not found.unresolved


def test_physical_stack_window_has_its_own_visible_bound():
    rom = make_rom(size=0x8000, code={0: bytes.fromhex("31f0df 00 f5 18fd")})
    found = sms_trace.Tracer(rom, limits=Limits(stack=1000, per_pc=1000)).follow({0: (0, "vector")})
    assert "physical stack tracking budget exhausted" in found.exhausted[0]


def test_pushed_af_cannot_invent_a_complete_return_address_from_a_alone():
    rom = make_rom(size=0x8000, code={0: bytes.fromhex("3e05 f5 c9"), 5: b"\xc9"})
    found = sms_trace.Tracer(rom).follow({0: (0, "vector")})
    assert 5 not in found.starts
    assert found.unresolved[0]


def test_popping_a_pair_into_af_uses_its_high_byte_for_the_accumulator():
    rom = make_rom(size=0x20000, code={0: bytes.fromhex("01ff05 c5 f1 32ffff cd0080 18fe"), 0x14000: b"\xc9"})
    found = sms_trace.Tracer(rom).follow({0: (0, "vector")})
    assert 0x14000 in found.starts


def test_mapper_shadow_store_cannot_overwrite_a_callers_live_return_word():
    rom = make_rom(size=0x20000, code={
        0: bytes.fromhex("3100e0 cd0002 cd0080 18fe"),
        0x200: bytes.fromhex("3e06 32ffff c9"), 0x18000: b"\xc9",
    })
    found = sms_trace.Tracer(rom).follow({0: (0, "vector")})
    assert 0x18000 not in found.starts
    assert "memory write aliases an active physical stack value" in found.unresolved[0]
