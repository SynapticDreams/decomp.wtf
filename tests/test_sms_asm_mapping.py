"""A matching CPU address/name does not establish a physical ROM reference."""
from dataclasses import replace

import pytest

from decompnet.rom import sms_asm, sms_asm_refs
from decompnet.rom.sms_mapping import BusState, Mapper

HEADER = ("; Routes one named handler and returns to the caller afterward.\n"
          "; Input: caller registers. Output: the handler's result and flags.\n")
NEEDS_WLA = pytest.mark.skipif(not sms_asm.available(), reason="needs WLA-DX")


def routine(target=0x8000, target_flat=0x14000, *, bank=0, cpu=0x200, **kwargs):
    flat = bank * 0x4000 + (cpu & 0x3FFF)
    return sms_asm.Routine("CallerEntry", bank, cpu, b"\xcd" + target.to_bytes(2, "little") + b"\xc9",
        {"CallerEntry": cpu, "Handler": target}, {flat: "CallerEntry", target_flat: "Handler"},
        {flat: cpu, target_flat: target}, **kwargs)


def source():
    return HEADER + "RouteEntry:\n    call Handler\n    ret\n"


def test_draft_leaves_a_unique_unknown_bank_numeric():
    r = routine()
    assert "call $8000" in sms_asm.draft(r)
    assert "call Handler" not in sms_asm.draft(r)
    assert sms_asm_refs.reference(r, 0x8000).space == "unknown"


def test_explicit_mapping_and_source_kinds_use_the_shared_model():
    state = BusState.cartridge_only((4, 1, 5))
    r = routine(mapping=state)
    model = Mapper("sega", r.banks * 0x4000)
    for target in (0x31, 0x1234, 0x4123, 0x8123, 0xC123):
        assert sms_asm_refs.reference(r, target) == model.resolve(target, state)
    for context in (replace(state, control=8), replace(state, bios=True), replace(state, cartridge=False), BusState()):
        assert sms_asm_refs.reference(replace(r, mapping=context), 0x8000).rom_offset is None


def test_an_indirect_read_does_not_invalidate_a_known_bank():
    r = routine(mapping=BusState.cartridge_only((0, 1, 5)))
    r.code = b"\x7e" + r.code  # ld a,(hl) reads memory; it does not select a bank
    assert sms_asm_refs.reference(r, 0x8000, 1).rom_offset == 0x14000


@NEEDS_WLA
@pytest.mark.parametrize(("encoded", "instruction"), [("ed67", "rrd"), ("edb2", "inir"), ("d300", "out ($00), a")])
def test_byte_correct_explicit_writes_cannot_accept_a_stale_named_rom_reference(encoded, instruction):
    r = routine(mapping=BusState.cartridge_only((0, 1, 5)))
    r.code = bytes.fromhex(encoded + " cd0080 c9")
    text = HEADER + f"RouteEntry:\n    {instruction}\n    call Handler\n    ret\n"
    verdict = sms_asm.judge(r, text)
    assert verdict.same == verdict.size == len(r.code)
    assert not verdict.ok and any(p.startswith("3.") and "isn't known yet" in p for p in verdict.problems)


@NEEDS_WLA
def test_a_unique_named_function_in_an_unknown_window_cannot_be_accepted():
    verdict = sms_asm.judge(routine(), source())
    assert verdict.same == verdict.size == 4
    assert not verdict.ok and any(p.startswith("3.") and "isn't known yet" in p for p in verdict.problems)


@NEEDS_WLA
def test_slot_zero_above_the_fixed_prefix_needs_mapping_evidence():
    verdict = sms_asm.judge(routine(0x1000, 0x1000, bank=5, cpu=0x8100), source())
    assert verdict.same == 4 and not verdict.ok
    assert any(p.startswith("3.") for p in verdict.problems)


@NEEDS_WLA
def test_known_paged_slot_zero_reference_is_accepted():
    r = routine(0x1000, 0x11000, bank=5, cpu=0x8100, mapping=BusState.cartridge_only((4, 1, 5)))
    verdict = sms_asm.judge(r, source())
    assert verdict.ok, verdict.problems
    assert "call Handler" in sms_asm.draft(r)


@NEEDS_WLA
def test_cartridge_ram_does_not_become_a_named_rom_function():
    verdict = sms_asm.judge(routine(mapping=BusState.cartridge_only((0, 1, 5), control=8)), source())
    assert verdict.same == 4 and not verdict.ok
    assert any(p.startswith("3.") and "cartridge RAM" in p for p in verdict.problems)


@NEEDS_WLA
def test_a_known_mapping_refuses_a_wrong_bank_even_when_its_name_is_unique():
    verdict = sms_asm.judge(routine(target_flat=0x18000, mapping=BusState.cartridge_only((0, 1, 5))), source())
    assert not verdict.ok and any("Handler is in bank 6" in p and "reaches bank 5" in p for p in verdict.problems)


@NEEDS_WLA
def test_fixed_prefix_cannot_name_the_same_cpu_address_in_another_physical_bank():
    verdict = sms_asm.judge(routine(0x31, 0x10031), source())
    assert verdict.same == 4 and not verdict.ok
    assert any("reaches bank 0" in p for p in verdict.problems)


@NEEDS_WLA
def test_mapperless_reference_is_flat_without_sega_reset_banks():
    verdict = sms_asm.judge(routine(target_flat=0x8000, mapper="mapperless", rom_size=0xC000, banks=3), source())
    assert verdict.ok, verdict.problems


@NEEDS_WLA
def test_source_placement_cannot_contradict_the_declared_mapper():
    verdict = sms_asm.judge(routine(0x31, 0x31, bank=1, cpu=0x8100,
                                    mapper="mapperless", rom_size=0xC000, banks=3), source())
    assert verdict.same == 4 and not verdict.ok
    assert any(p.startswith("3.") and "source coordinate" in p for p in verdict.problems)


@NEEDS_WLA
def test_a_mapper_write_cannot_leave_the_previous_entry_bank_as_a_reference_fact():
    r = routine(0x8200, 0x14200, bank=5, cpu=0x8100)
    r.code = bytes.fromhex("3e06 32ffff cd0082 c9")
    text = HEADER.replace("Routes one named handler", "Maps a bank and routes one named handler") + \
        "RouteEntry:\n    ld a, 6\n    ld (MapperSlot2), a\n    call Handler\n    ret\n"
    verdict = sms_asm.judge(r, text)
    assert verdict.same == len(r.code) and not verdict.ok
    assert any(p.startswith("3.") for p in verdict.problems)
    assert "call $8200" in sms_asm.draft(r)


@NEEDS_WLA
def test_typed_data_cannot_hide_a_following_mapper_write_from_reference_checks():
    r = routine(0x8200, 0x14200, bank=5, cpu=0x8100)
    r.code = bytes.fromhex("3e06 cd00 32ffff cd0082 c9")
    r.data = [(r.flat + 2, 2, "inline")]
    text = HEADER.replace("Routes one named handler", "Maps a bank and routes one named handler") + \
        "RouteEntry:\n    ld a, 6\n    .db $cd, $00\n    ld (MapperSlot2), a\n    call Handler\n    ret\n"
    verdict = sms_asm.judge(r, text)
    assert verdict.same == len(r.code) and not verdict.ok
    assert any(p.startswith("3.") for p in verdict.problems)
    assert "call $8200" in sms_asm.draft(r)


@NEEDS_WLA
def test_a_call_without_a_return_contract_cannot_preserve_a_named_reference():
    state = BusState.cartridge_only((0, 1, 5))
    r = sms_asm.Routine("CallerEntry", 5, 0x8100, bytes.fromhex("cd0002 cd0082 c9"),
                        {"CallerEntry": 0x8100, "FixedHelper": 0x200, "Handler": 0x8200},
                        {0x14100: "CallerEntry", 0x200: "FixedHelper", 0x14200: "Handler"},
                        {0x14100: 0x8100, 0x200: 0x200, 0x14200: 0x8200}, mapping=state)
    text = HEADER + "RouteEntry:\n    call FixedHelper\n    call Handler\n    ret\n"
    verdict = sms_asm.judge(r, text)
    assert verdict.same == verdict.size == 7
    assert not verdict.ok and any(p.startswith("3.") and "isn't known yet" in p for p in verdict.problems)
    assert "call $8200" in sms_asm.draft(r)


@NEEDS_WLA
@pytest.mark.parametrize(("encoded", "instruction"), [("fb", "ei"), ("76", "halt"), ("310000", "ld sp, $0000")])
def test_interrupt_or_stack_relocation_cannot_supply_a_named_rom_contract(encoded, instruction):
    r = routine(0x8200, 0x14200, bank=5, cpu=0x8100, mapping=BusState.cartridge_only((0, 1, 5)))
    r.code = bytes.fromhex(encoded + " cd0082 c9")
    text = HEADER + f"RouteEntry:\n    {instruction}\n    call Handler\n    ret\n"
    verdict = sms_asm.judge(r, text)
    assert verdict.same == verdict.size == len(r.code)
    assert not verdict.ok and any(p.startswith("3.") and "isn't known yet" in p for p in verdict.problems)
