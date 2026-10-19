"""Explicit Z80 writes must not leave stale mapper, RAM or saved-value facts."""
import pytest

from dataclasses import replace

from decompnet.rom import sms_asm, sms_asm_refs, sms_trace
from decompnet.rom.sms_effects import memory_writes
from decompnet.rom.sms_mapping import Mapper

from .test_sms import make_rom


@pytest.mark.parametrize("write", ["3606", "1200", "edb0", "edb2", "ed67", "dd360006"])
def test_unqualified_memory_write_cannot_preserve_a_bank(write):
    rom = make_rom(size=0x20000, code={
        0: bytes.fromhex("3e05 32ffff " + write + " cd0080 18fe"),
        0x14000: bytes.fromhex("3e05 c9"),
    })
    found = sms_trace.Tracer(rom).follow({0: (0, "vector")})
    assert 0x14000 not in found.starts


@pytest.mark.parametrize("restore", ["3affff", "f1"])
def test_unknown_store_invalidates_ram_readback_and_saved_stack_values(restore):
    rom = make_rom(size=0x20000, code={
        0: bytes.fromhex("3e05 32ffff f5 3606 3e00 32fcff " + restore + " 32ffff cd0080 18fe"),
        0x14000: bytes.fromhex("3e05 c9"),
    })
    found = sms_trace.Tracer(rom).follow({0: (0, "vector")})
    assert 0x14000 not in found.starts


def test_word_store_changes_both_mapper_registers():
    rom = make_rom(size=0x20000, code={
        0: bytes.fromhex("3e05 32ffff 210106 22feff cd0080 18fe"),
        0x14000: bytes.fromhex("3e05 c9"), 0x18000: bytes.fromhex("3e06 c9"),
    })
    found = sms_trace.Tracer(rom).follow({0: (0, "vector")})
    assert 0x18000 in found.starts and 0x14000 not in found.starts


@pytest.mark.parametrize("write", ["d33e", "d300", "ed79", "edb3"])
def test_possible_memory_control_port_write_stops_cartridge_assumptions(write):
    rom = make_rom(size=0x20000, code={
        0: bytes.fromhex("3e05 32ffff " + write + " cd0080 18fe"),
        0x14000: bytes.fromhex("3e05 c9"),
    })
    found = sms_trace.Tracer(rom).follow({0: (0, "vector")})
    assert 0x14000 not in found.starts


@pytest.mark.parametrize("write", ["d3be", "d33f", "01be00 ed79", "01be03 edb3"])
def test_known_vdp_and_io_control_outputs_preserve_cartridge_banks(write):
    rom = make_rom(size=0x20000, code={
        0: bytes.fromhex("3e05 32ffff " + write + " cd0080 18fe"),
        0x14000: bytes.fromhex("3e05 c9"),
    })
    found = sms_trace.Tracer(rom).follow({0: (0, "vector")})
    assert 0x14000 in found.starts


@pytest.mark.parametrize("write", ["11ffff 12", "01ffff 02", "21ffff 75"])
def test_known_indirect_addresses_and_register_values_select_a_bank(write):
    # DE/BC stores use A=6; the HL store uses L=$FF, selecting bank 7 on this cartridge.
    expected = 0x1C000 if write.endswith("75") else 0x18000
    rom = make_rom(size=0x20000, code={
        0: bytes.fromhex("3e06 " + write + " cd0080 18fe"), expected: bytes.fromhex("3e01 c9"),
    })
    assert expected in sms_trace.Tracer(rom).follow({0: (0, "vector")}).starts


def test_word_store_to_ram_alias_updates_readback_without_selecting_a_bank():
    rom = make_rom(size=0x20000, code={
        0: bytes.fromhex("3e05 32ffff 210006 22fedf cd0080 3affff 32ffff cd0080 18fe"),
        0x14000: bytes.fromhex("3e05 c9"), 0x18000: bytes.fromhex("3e06 c9"),
    })
    found = sms_trace.Tracer(rom).follow({0: (0, "vector")})
    assert {0x14000, 0x18000} <= found.starts.keys()


def test_mapperless_writes_do_not_invent_sega_register_effects():
    rom = make_rom(size=0xC000, code={0: bytes.fromhex("3606 cd0080 18fe"), 0x8000: b"\xc9"})
    assert 0x8000 in sms_trace.Tracer(rom, mapper="mapperless").follow({0: (0, "vector")}).starts


@pytest.mark.parametrize("write", ["ed67", "edb2", "d300", "edb3", "ddcb0006"])
def test_assembly_reference_checks_share_explicit_write_invalidation(write):
    model = Mapper("sega", 0x20000)
    mapping = replace(model.reset(), banks=(0, 1, 5))
    code = bytes.fromhex(write + " cd0080 c9")
    routine = sms_asm.Routine("Caller", 0, 0x200, code, {}, {0x200: "Caller", 0x14000: "Handler"},
                              {0x200: 0x200, 0x14000: 0x8000}, mapping=mapping, rom_size=model.size)
    assert sms_asm_refs.reference(routine, 0x8000, len(bytes.fromhex(write))).rom_offset is None


def test_word_store_wraps_and_reads_do_not_become_stores():
    writes = memory_writes("ld ($ffff), hl", {"hl": 0x0605})
    assert [(write.cpu, write.value) for write in writes] == [(0xFFFF, 5), (0, 6)]
    assert memory_writes("ld hl, ($ffff)") == ()
    assert memory_writes("bit 3, (hl)") == ()


def test_indexed_cb_register_copy_cannot_leave_a_stale_bank_value():
    rom = make_rom(size=0x20000, code={
        # An indexed memory rotate copies an unknown result into A. Reinitialize control before using A
        # through the stack; source-memory uncertainty must not let its earlier A=5 escape the instruction.
        0: bytes.fromhex("3e05 ddcb0007 f5 3e00 32fcff f1 32ffff cd0080 18fe"),
        0x14000: bytes.fromhex("3e05 c9"),
    })
    assert 0x14000 not in sms_trace.Tracer(rom).follow({0: (0, "vector")}).starts


@pytest.mark.parametrize("opcode", ["ed67", "ed6f"])
def test_nibble_rotate_invalidates_a_even_when_its_memory_address_is_known(opcode):
    rom = make_rom(size=0x20000, code={
        0: bytes.fromhex("3e05 2100c0 " + opcode + " 32ffff cd0080 18fe"),
        0x14000: bytes.fromhex("3e05 c9"),
    })
    assert 0x14000 not in sms_trace.Tracer(rom).follow({0: (0, "vector")}).starts


@pytest.mark.parametrize(("setup", "write"), [("01ffff cb80", "02"), ("11ffff cb83", "12"),
                                                ("21ffff cb84", "77"), ("11ffff ed50", "12")])
def test_changed_register_halves_cannot_supply_a_stale_indirect_mapper_address(setup, write):
    rom = make_rom(size=0x20000, code={
        0: bytes.fromhex("3e05 32ffff " + setup + " 3e06 " + write + " cd0080 18fe"),
        0x14000: bytes.fromhex("3e05 c9"), 0x18000: bytes.fromhex("3e06 c9"),
    })
    found = sms_trace.Tracer(rom).follow({0: (0, "vector")})
    assert 0x18000 not in found.starts


def test_popping_an_untracked_index_register_consumes_its_saved_stack_value():
    rom = make_rom(size=0x20000, code={
        0: bytes.fromhex("3e05 f5 3e06 f5 dde1 f1 32ffff cd0080 18fe"),
        0x14000: bytes.fromhex("3e05 c9"), 0x18000: bytes.fromhex("3e06 c9"),
    })
    found = sms_trace.Tracer(rom).follow({0: (0, "vector")})
    assert 0x14000 in found.starts and 0x18000 not in found.starts


@pytest.mark.parametrize("change", ["31f0df", "33", "3b"])
def test_sp_changes_cannot_restore_an_old_virtual_stack_value(change):
    rom = make_rom(size=0x20000, code={
        0: bytes.fromhex("3e05 f5 " + change + " f1 32ffff cd0080 18fe"),
        0x14000: bytes.fromhex("3e05 c9"),
    })
    assert 0x14000 not in sms_trace.Tracer(rom).follow({0: (0, "vector")}).starts
