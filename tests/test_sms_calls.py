"""Callee writes must affect the caller's continuation under its actual incoming facts."""
import pytest

from decompnet.rom import sms, sms_trace
from decompnet.rom.sms_paths import Limits

from .test_sms import make_rom


def follow(callee, *, call="cd0002", after="cd0080", extra=None, **kwargs):
    rom = make_rom(size=0x20000, code={
        0: bytes.fromhex("3e05 32ffff " + call + " " + after + " 18fe"),
        0x200: bytes.fromhex(callee),
        0x14000: bytes.fromhex("3e05 c9"), 0x18000: bytes.fromhex("3e06 c9"),
        **(extra or {}),
    })
    return sms_trace.Tracer(rom, **kwargs).follow({0: (0, "vector")})


def test_fixed_bank_write_in_a_callee_changes_the_callers_mapping():
    found = follow("3e06 32ffff c9")
    assert 0x18000 in found.starts and 0x14000 not in found.starts


def test_callee_control_write_can_select_ram_in_the_callers_window():
    found = follow("3e08 32fcff c9")
    assert 0x14000 not in found.starts


def test_callee_ram_alias_write_changes_readback_without_a_mapper_write():
    found = follow("3e06 32ffdf c9", after="3affff 32ffff cd0080")
    assert 0x18000 in found.starts and 0x14000 not in found.starts


@pytest.mark.parametrize("callee", ["3606 c9", "d33e c9"])
def test_unqualified_callee_effects_cannot_preserve_a_singleton_bank(callee):
    assert 0x14000 not in follow(callee).starts


def test_conditional_call_joins_called_and_uncalled_mapper_states():
    found = follow("3e06 32ffff c9", call="cc0002")
    assert 0x14000 not in found.starts and 0x18000 not in found.starts


def test_nested_tail_callee_changes_reach_the_original_caller():
    found = follow("c30003", extra={0x300: bytes.fromhex("3e06 32ffff c9")})
    assert 0x18000 in found.starts and 0x14000 not in found.starts


def test_mapper_helper_uses_the_actual_callers_argument():
    found = follow("32ffff c9", call="3e06 cd0002")
    assert 0x18000 in found.starts and 0x14000 not in found.starts


def test_divergent_return_paths_join_their_mapper_values():
    found = follow("2801 c9 3e06 32ffff c9")
    assert 0x14000 not in found.starts and 0x18000 not in found.starts


def test_slot_zero_and_ram_control_return_together():
    found = follow("3e04 32fdff 3e08 32fcff c9", after="cd0010 cd0080",
                   extra={0x11000: b"\xc9", 0x1000: b"\xc9"})
    assert 0x11000 in found.starts and 0x1000 not in found.starts and 0x14000 not in found.starts


def test_nested_save_change_call_restore_preserves_the_actual_ram_shadow():
    found = follow("3affff f5 3e06 32ffff cd0080 f1 32ffff c9")
    assert {0x14000, 0x18000} <= found.starts.keys()
    assert all(state.banks[2] == 5 for state in found.entered[0x14000])


def test_computed_callee_effects_apply_before_the_pushed_continuation():
    found = follow("210003 110802 d5 e9 cd0080 c9", extra={0x300: bytes.fromhex("3e06 32ffff c9")})
    assert 0x18000 in found.starts and 0x14000 not in found.starts


def test_inline_return_address_adjustment_requires_agreed_paths_or_its_declared_continuation():
    callee = "e1 23 e5 c9"  # every path returns one byte past the call
    assert 0x14000 in follow(callee, after="00 cd0080").starts
    assert 0x14000 in follow(callee, after="00 cd0080", hints={"inline": {0x200: 1}}).starts
    maybe = "e1 b7 2801 23 e5 c9"  # one byte past only on a path the flags choose
    assert 0x14000 not in follow(maybe, after="00 cd0080").starts
    assert 0x14000 not in follow(callee, after="00 cd0080", hints={"inline": {0x200: 2}}).starts


def test_explicit_noreturn_correction_stops_a_returning_synthetic_callee():
    assert 0x14000 not in follow("c9", hints={"noreturn": {0x200}}).starts


@pytest.mark.parametrize("callee", ["fb c9", "76 c9", "ed4d", "ed45", "e3 c9", "31f0df c9"])
def test_interrupt_and_unqualified_stack_cases_report_unresolved(callee):
    found = follow(callee)
    assert 0x14000 not in found.starts
    assert found.unresolved[0]


@pytest.mark.parametrize(("callee", "kwargs", "reason"), [
    ("000000000000 c9", {"call_limits": Limits(steps=3)}, "call instruction budget exhausted"),
    ("cd0002 c9", {"call_depth": 2}, "call depth budget exhausted"),
    ("00 f5 18fd", {"call_limits": Limits(stack=2)}, "stack budget exhausted"),
])
def test_call_budgets_discard_incomplete_singleton_effects(callee, kwargs, reason):
    found = follow(callee, **kwargs)
    assert reason in found.exhausted[0]
    assert reason in found.unresolved[0]
    assert 0x14000 not in found.starts


def test_call_into_selected_ram_cannot_establish_a_later_rom_restore():
    rom = make_rom(size=0x20000, code={
        0: bytes.fromhex("3e05 32ffff 3e08 32fcff cd0080 3e00 32fcff cd0080 18fe"),
        0x14000: bytes.fromhex("3e05 c9"),
    })
    found = sms_trace.Tracer(rom).follow({0: (0, "vector")})
    assert 0x14000 not in found.starts
    assert "callee instruction source is unresolved or declared data" in found.unresolved[0]


def test_unresolved_callee_effects_reach_split_reports_and_logs():
    rom = make_rom(size=0x20000, code={0: bytes.fromhex("cd0002 18fe"), 0x200: bytes.fromhex("d33e c9")})
    report, logs = {}, []
    sms.functions(rom, report=report, log=logs.append)
    assert any(row["rom_offset"] == 0 for row in report["analysis_unresolved"])
    assert any("execution effects remain unresolved" in line for line in logs)


def test_callee_self_paging_changes_the_callers_next_instruction_source():
    rom = make_rom(size=0x20000, code={
        0: bytes.fromhex("c30010"),
        0x1000: bytes.fromhex("cd0002 cd5002 c9"),
        0x11003: bytes.fromhex("cd0003 c9"),
        0x200: bytes.fromhex("3e04 32fdff c9"), 0x250: b"\xc9", 0x300: b"\xc9",
    })
    found = sms_trace.Tracer(rom).follow({0: (0, "vector")})
    assert 0x11003 in found.code and 0x1003 not in found.code
    assert 0x300 in found.starts and 0x250 not in found.starts


def test_closed_callee_loop_does_not_invent_a_return_continuation():
    found = follow("18fe", after="cd0003", extra={0x300: b"\xc9"})
    assert 0x300 not in found.starts and not found.unresolved


def test_nested_targets_derived_from_a_callers_argument_are_discovery_entries():
    found = follow("32ffff cd0080 c9", call="3e06 cd0002", after="")
    assert 0x18000 in found.starts and 0x14000 not in found.starts


def test_unresolved_callee_report_is_available_in_a_read_only_resplit(tmp_path):
    from decompnet.app.engine import RomNetwork

    net = RomNetwork(tmp_path / "app.db", tmp_path / "work")
    net.auto_install_tools = False
    image = make_rom(size=0x8000, code={0: bytes.fromhex("cd0002 18fe"), 0x200: bytes.fromhex("d33e c9")})
    slug = net.import_rom(image, confirmed=True, name="fixture.sms", log=lambda *_: None)
    before = [dict(row) for row in net.store.all("SELECT * FROM functions")]
    result = net.resplit_banked(slug, apply=False, log=lambda *_: None)
    assert any(row["rom_offset"] == 0 for row in result["analysis_unresolved"])
    assert [dict(row) for row in net.store.all("SELECT * FROM functions")] == before
