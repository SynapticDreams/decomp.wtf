"""Full bus contexts survive calls and joins; RAM selection cannot manufacture ROM targets."""
from dataclasses import replace

from decompnet.rom import sms_trace
from decompnet.rom.sms_mapping import BusState, Mapper, join

from .test_sms import make_rom


def follow(code, *, size=0x20000, **kwargs):
    return sms_trace.Tracer(make_rom(size=size, code=code), **kwargs).follow({0: (0, "vector")})


def test_slot_zero_selection_survives_a_call_through_the_fixed_prefix():
    found = follow({0: bytes.fromhex("3e04 32fdff cd0002 18fe"),
                    0x200: bytes.fromhex("cd0010 c9"), 0x11000: bytes.fromhex("3e04 c9"),
                    0x1000: bytes.fromhex("3e00 c9")})
    assert found.starts[0x11000] == (0x1000, "call")
    assert 0x1000 not in found.starts
    assert all(state.banks[0] == 4 for state in found.entered[0x200])


def test_cartridge_ram_selection_survives_a_call_instead_of_resolving_rom():
    found = follow({0: bytes.fromhex("3e05 32ffff 3e08 32fcff cd0002 18fe"),
                    0x200: bytes.fromhex("cd0080 c9"), 0x14000: bytes.fromhex("3e05 c9")})
    assert 0x14000 not in found.starts
    assert all(state.control == 8 for state in found.entered[0x200])


def test_restoring_rom_selection_uses_the_preserved_bank():
    found = follow({0: bytes.fromhex("3e05 32ffff 3e08 32fcff cd0080 3e00 32fcff cd0080 18fe"),
                    0x14000: bytes.fromhex("3e05 c9")})
    assert found.starts[0x14000] == (0x8000, "call")
    assert all(state.control == 0 and state.banks[2] == 5 for state in found.entered[0x14000])


def test_unknown_control_does_not_assume_slot_two_is_rom():
    found = follow({0: bytes.fromhex("3a00c0 32fcff cd0080 18fe"), 0x8000: bytes.fromhex("3e02 c9")})
    assert 0x8000 not in found.starts


def test_work_ram_readback_is_not_reused_when_cartridge_ram_may_contend():
    found = follow({0: bytes.fromhex("3e06 3200c1 3e10 32fcff 3a00c1 32ffff 3e00 32fcff cd0080 18fe"),
                    0x18000: bytes.fromhex("3e06 c9")})
    assert 0x18000 not in found.starts


def test_conflicting_ram_selection_at_callers_stays_unknown_in_the_callee():
    found = follow({0: bytes.fromhex("3e05 32ffff 3e08 32fcff cd0002 3e00 32fcff cd0002 18fe"),
                    0x200: bytes.fromhex("cd0080 c9"), 0x14000: bytes.fromhex("3e05 c9")})
    assert 0x14000 not in found.starts
    assert {state.control for state in found.entered[0x200]} == {0, 8}


def test_instruction_after_self_paging_is_fetched_from_the_new_bank():
    found = follow({0: bytes.fromhex("3e05 32ffff c30080"),
                    0x14000: bytes.fromhex("3e06 32ffff cd0001 c9"),
                    0x18005: bytes.fromhex("cd0002 c9"), 0x100: b"\xc9", 0x200: b"\xc9"})
    assert 0x18005 in found.code and 0x14005 not in found.code
    assert 0x200 in found.starts and 0x100 not in found.starts


def test_small_sega_cartridges_still_have_mapper_registers():
    found = follow({0: bytes.fromhex("3e01 32ffff cd0002 18fe"), 0x200: bytes.fromhex("cd0080 c9"),
                    0x4000: bytes.fromhex("3e01 c9")}, size=0xC000)
    assert found.starts[0x4000] == (0x8000, "call")


def test_mapperless_explicit_selection_ignores_mapper_writes():
    found = follow({0: bytes.fromhex("3e01 32ffff cd0080 18fe"), 0x8000: bytes.fromhex("3e02 c9")},
                   size=0xC000, mapper="mapperless")
    assert found.starts[0x8000] == (0x8000, "call")


def test_unknown_or_bios_reset_does_not_trace_cartridge_bytes():
    for reset in (BusState(), replace(Mapper("sega", 0x20000).reset(), bios=True, cartridge=False)):
        found = follow({0: bytes.fromhex("cd0001 18fe"), 0x100: b"\xc9"}, reset=reset)
        assert not found.code and 0x100 not in found.starts


def test_join_retains_only_common_bus_facts_and_keeps_possible_rom_modification():
    base = Mapper("sega", 0x20000).reset()
    mixed = join([base, replace(base, control=8, bios=True, rom_modified=True)])
    assert mixed.control is None and mixed.bios is None and mixed.banks == base.banks
    assert mixed.cartridge is True and mixed.rom_modified is True
    assert join([base, base]) == base
    assert join([]) == BusState()
