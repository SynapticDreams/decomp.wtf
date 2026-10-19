"""Distinct paths, converging loops and visible limits on incomplete static discovery."""
from dataclasses import replace

import pytest

from decompnet.rom import sms, sms_trace
from decompnet.rom.sms_mapping import Mapper
from decompnet.rom.sms_paths import Limits, Paths, signature
from decompnet.rom.sms_state import FRESH, State

from .test_sms import make_rom


def test_control_values_joining_at_one_store_both_reach_the_callee():
    rom = make_rom(size=0x20000, code={
        0: bytes.fromhex("3e05 32ffff 2804 3e08 1802 3e00 32fcff cd0002 18fe"),
        0x200: bytes.fromhex("cd0080 c9"), 0x14000: bytes.fromhex("3e05 c9"),
    })
    found = sms_trace.Tracer(rom).follow({0: (0, "vector")})
    assert {state.control for state in found.entered[0x200]} == {0, 8}
    assert found.unresolved[0x200]  # joined callers cannot prove that slot 2 contains ROM
    assert all(state.control_flag(8) is False for state in found.entered[0x14000])  # conditional ROM path only


def test_push_history_belongs_to_the_path_that_pushed():
    rom = make_rom(size=0x8000, code={0: bytes.fromhex("2802 f5 c9 e1 c9")})
    found = sms_trace.Tracer(rom).follow({0: (0, "vector")})
    assert 0 in found.takes_return  # the other path pops HL before pushing anything


def test_context_exhaustion_removes_singleton_caller_mapping_and_helper_claims():
    rom = make_rom(size=0x20000, code={
        0: bytes.fromhex("3e05 32ffff 2804 3e08 1802 3e00 32fcff cd0002 18fe"),
        0x200: bytes.fromhex("cd0080 c9"), 0x14000: bytes.fromhex("3e05 c9"),
    })
    found = sms_trace.Tracer(rom, limits=Limits(per_pc=1)).follow({0: (0, "vector")})
    assert "context budget exhausted" in found.exhausted[0]
    assert 0x200 in found.starts and 0x14000 not in found.starts
    assert all(state.banks[2] is None for state in found.entered[0x200])
    assert 0 not in found.switchers


def test_exhausted_callee_cannot_hide_the_callers_continuation():
    rom = make_rom(size=0x8000, code={
        0: bytes.fromhex("cd0002 cd0003 18fe"),
        0x200: bytes.fromhex("0000000000000000000000 c9"), 0x300: b"\xc9",
    })
    found = sms_trace.Tracer(rom, limits=Limits(steps=6)).follow({0: (0, "vector")})
    assert "instruction budget exhausted" in found.exhausted[0x200]
    assert 0x300 in found.starts


@pytest.mark.parametrize(("code", "limits", "reason"), [
    ("00 f5 18fd", Limits(stack=2), "stack budget exhausted"),
    ("2100c0 3601 23 18fb", Limits(memory=2), "memory budget exhausted"),
])
def test_growing_stack_and_ram_paths_stop_with_a_reason(code, limits, reason):
    rom = make_rom(size=0x8000, code={0: bytes.fromhex(code)})
    found = sms_trace.Tracer(rom, limits=limits).follow({0: (0, "vector")})
    assert reason in found.exhausted[0]


def test_unchanged_loop_converges_after_fresh_bounds_expire():
    state = State(Mapper("sega", 0x8000).reset(), n=3, bound=(3, 3, True))
    paths = Paths(Limits(steps=100))
    for age in range(FRESH + 2):
        state.n = 3 + age
        assert paths.admit(2, 2, state)
    state.n += 1
    assert not paths.admit(2, 2, state)  # both states now have an expired bound
    assert not paths.exhausted
    rom = make_rom(size=0x8000, code={0: bytes.fromhex("e603 18fe")})
    assert not sms_trace.Tracer(rom).follow({0: (0, "vector")}).exhausted


def test_signature_uses_relative_age_but_retains_register_memory_and_stack_facts():
    state = State(Mapper("sega", 0x8000).reset(), n=10, a=5, bound=(10, 3, True))
    assert signature(state) == signature(replace(state, n=100, bound=(100, 3, True)))
    for changed in (replace(state, a=6), replace(state, mem={0xC100: 6}),
                    replace(state, stack=[5]), replace(state, bound=(9, 3, True)),
                    replace(state, mapping=Mapper("sega", 0x8000).write(state.mapping, 0xFFFC, 8))):
        assert signature(state) != signature(changed)


@pytest.mark.parametrize("bad", [0, -1, True, 1.5, 1_000_001])
def test_invalid_limits_are_rejected(bad):
    with pytest.raises(ValueError):
        Limits(steps=bad)


def test_exhaustion_is_reported_and_logged_through_function_discovery():
    rom = make_rom(size=0x8000, code={0: bytes.fromhex("00 f5 18fd")})
    report, logs = {}, []
    sms.functions(rom, report=report, log=logs.append, limits=Limits(stack=2))
    assert {"rom_offset": 0, "reasons": ["stack budget exhausted"]} in report["analysis_exhausted"]
    assert any("remain incomplete" in line for line in logs)
    assert any("ROM offset 0: stack budget exhausted" in line for line in logs)


def test_resplit_preview_exposes_exhaustion_without_applying_changes(tmp_path, monkeypatch):
    from decompnet.app.engine import RomNetwork

    net = RomNetwork(tmp_path / "app.db", tmp_path / "work")
    net.auto_install_tools = False
    rom = tmp_path / "fixture.sms"
    rom.write_bytes(make_rom(size=0x8000, code={0: bytes.fromhex("00 f5 18fd")}))
    slug = net.import_rom(rom, confirmed=True, log=lambda *_: None)
    before = [dict(row) for row in net.store.all("SELECT * FROM functions")]
    monkeypatch.setattr(sms_trace, "Limits", lambda: Limits(stack=2))
    preview = net.resplit_banked(slug, apply=False, log=lambda *_: None)
    assert {"rom_offset": 0, "reasons": ["stack budget exhausted"]} in preview["analysis_exhausted"]
    assert [dict(row) for row in net.store.all("SELECT * FROM functions")] == before
