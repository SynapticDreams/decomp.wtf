"""Whole-analysis limits and entry back-edges must preserve explicit incompleteness."""
import pytest
from dataclasses import replace

from decompnet.rom import sms, sms_trace
from decompnet.rom.sms_analysis import AnalysisLimits, Budget
from decompnet.rom.sms_mapping import BusState, Mapper

from .test_sms import make_rom


def test_own_entry_backedge_revisits_new_ram_and_mapper_facts_without_resetting():
    rom = make_rom(size=0x20000, code={
        0: bytes.fromhex("3affff 32feff 2803 cd0040 3e05 32ffff c30000"),
        0x14000: b"\xc9",
    })
    found = sms_trace.Tracer(rom).follow({0: (0, "vector")})
    assert found.starts[0x14000] == (0x4000, "call")
    assert all(state.banks[1] == 5 for state in found.entered[0x14000])


def test_candidate_output_truncation_has_an_explicit_report():
    rom = make_rom(size=0x8000, code={0: bytes.fromhex("cd0001 18fe"), 0x100: b"\xc9"})
    report = {}
    starts, _ = sms.candidates(rom, limit=1, report=report)
    assert len(starts) == 1
    assert "candidate output limit exhausted" in report.get("analysis_limits", {}).get("exhausted", [])
    assert report["analysis_limits"]["candidate_output_limit"] == 1


def test_unconverged_round_limit_is_visible_instead_of_looking_complete():
    rom = make_rom(size=0x8000, code={0: bytes.fromhex("cd0001 18fe"), 0x100: b"\xc9"})
    found = sms_trace.Tracer(rom).follow({0: (0, "vector")}, rounds=1)
    assert any("convergence round budget exhausted" in reasons for reasons in found.exhausted.values())
    assert all(state.control_bits(255) is None for state in found.entered[0x100])


@pytest.mark.parametrize(("limits", "reason"), [
    (AnalysisLimits(entries=1), "analysis entry budget exhausted"),
    (AnalysisLimits(instructions=3), "analysis instruction budget exhausted"),
    (AnalysisLimits(call_instructions=2), "analysis call instruction budget exhausted"),
    (AnalysisLimits(rounds=1), "analysis round budget exhausted"),
])
def test_global_limits_bound_calls_and_tracing_without_exporting_stale_contexts(limits, reason):
    rom = make_rom(size=0x20000, code={
        0: bytes.fromhex("3e05 32ffff cd0002 cd0080 18fe"),
        0x200: bytes.fromhex("0000000000 c9"), 0x14000: bytes.fromhex("3e05 c9"),
    })
    budget = Budget(limits)
    found = sms_trace.Tracer(rom, budget=budget).follow({0: (0, "vector")})
    assert reason in budget.exhausted
    assert reason in found.exhausted[0]
    used = budget.report()["used"]
    assert all(used[name] <= value for name, value in budget.report()["limits"].items())
    assert all(state.banks[2] is None and state.registers == (None, None, None) for state in found.entered[0])


def test_later_discovery_passes_share_global_rounds_and_keep_partial_results():
    rom = make_rom(size=0x8000, code={0: bytes.fromhex("c30001"), 0x100: bytes.fromhex("c9 3e01 c9")})
    report = {}
    starts, _ = sms.candidates(rom, report=report, analysis_limits=AnalysisLimits(rounds=4))
    assert 0x100 in starts
    assert report["analysis_limits"]["used"]["rounds"] == 4
    assert "analysis round budget exhausted" in report["analysis_limits"]["exhausted"]


def test_oversized_seed_set_is_bounded_and_disclosed():
    rom = make_rom(size=0x8000, code={0: b"\xc9", 0x100: b"\xc9", 0x200: b"\xc9"})
    budget = Budget(AnalysisLimits(entries=2))
    found = sms_trace.Tracer(rom, budget=budget).follow({at: (at, "hint") for at in (0, 0x100, 0x200)})
    assert len(found.starts) <= 2 and len(budget.entries) <= 2
    assert "analysis entry seed limit exhausted" in budget.exhausted


def test_converged_small_analysis_does_not_report_exhaustion():
    rom = make_rom(size=0x8000, code={0: bytes.fromhex("cd0001 18fe"), 0x100: b"\xc9"})
    budget = Budget()
    found = sms_trace.Tracer(rom, budget=budget).follow({0: (0, "vector")})
    assert not budget.exhausted and not found.exhausted


@pytest.mark.parametrize("bad", [0, -1, True, 1.5, 16_000_001])
def test_invalid_analysis_limits_cannot_disable_bounds(bad):
    with pytest.raises(ValueError):
        AnalysisLimits(instructions=bad)


def test_global_exhaustion_is_logged_with_limits_and_usage():
    rom = make_rom(size=0x8000, code={0: bytes.fromhex("cd0001 18fe"), 0x100: b"\xc9"})
    logs, report = [], {}
    sms.functions(rom, log=logs.append, report=report, analysis_limits=AnalysisLimits(rounds=1))
    assert report["analysis_limits"]["used"]["rounds"] == 1
    assert any("static discovery is incomplete" in line for line in logs)


def test_gap_discovery_pass_limit_does_not_hide_remaining_candidates():
    rom = make_rom(size=0x8000, code={0: bytes.fromhex("c30001"), 0x100: b"\xc9" * 20})
    report = {}
    starts, _ = sms.candidates(rom, report=report)
    assert 0x100 in starts
    assert "gap discovery pass budget exhausted" in report["analysis_limits"]["exhausted"]


@pytest.mark.parametrize("reset", [BusState(), replace(Mapper("sega", 0x8000).reset(), bios=True, cartridge=False),
                                   replace(Mapper("sega", 0x8000).reset(), rom_modified=True)])
def test_truncation_cannot_turn_an_unqualified_source_into_original_rom(reset):
    rom = make_rom(size=0x8000, code={0: b"\xc9"})
    model = Mapper("sega", len(rom))
    budget = Budget(AnalysisLimits(rounds=1))
    found = sms_trace.Tracer(rom, reset=reset, budget=budget).follow({0: (0, "vector")})
    assert budget.exhausted and not found.code
    assert all(model.resolve(0, state).rom_offset is None for state in found.entered[0])


def test_low_global_budget_starts_with_reset_instead_of_an_isolated_vector():
    rom = make_rom(size=0x8000, code={0: bytes.fromhex("3e05 32ffff 18fe"),
                                    **{at: b"\xc9" for at in sms.VECTORS if at}})
    report = {}
    starts, _ = sms.candidates(rom, report=report, analysis_limits=AnalysisLimits(instructions=3))
    assert 0 in starts
    assert report["analysis_limits"]["used"]["instructions"] == 3
    assert "analysis instruction budget exhausted" in report["analysis_limits"]["exhausted"]
