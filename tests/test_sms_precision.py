"""Precision a real program needed (the zexall-sms fixture, tools/sms_fixtures.py), each kept conservative:

- `(c)` port I/O decodes C alone, so `ld b, n / ld c, $bf / otir` reaches a known VDP port even with B unknown;
- after a call whose effects stay unresolved, the continuation keeps only its own window's geometry (as an
  isolated entry does): calls into that window resolve, other windows stay unknown;
- a block copy wholly within $C000-$DFFF is a RAM write, not an unknown store that may select banks or alter ROM;
- the same call from the same facts is evaluated once per trace."""

from __future__ import annotations

from decompnet.rom import sms, sms_calls, sms_effects, sms_registers, sms_trace
from decompnet.rom.sms_mapping import Mapper
from decompnet.rom.sms_state import State

from .test_sms import make_rom

SIZE = 0x20000
SEGA = Mapper("sega", SIZE)
BANK5 = {0x14000: bytes.fromhex("3e07c9")}  # bank 5 at $8000: ld a,7 · ret
TO_BANK5 = "3e05" "32ffff"  # ld a,5 · ld ($ffff),a


def found(main: str, at: int = 0x0100, **routines: str):
    """Reset jumps to `main` at `at` (part of the reset entry, whose findings are keyed at 0)."""
    vectors = {at: b"\xc9" for at in sms.VECTORS if at}
    code = {0x0000: bytes([0xC3, at & 0xFF, at >> 8]), at: bytes.fromhex(main), **BANK5}
    code.update({int(at[1:], 16): bytes.fromhex(body) for at, body in routines.items()})
    return sms_trace.Tracer(make_rom(size=SIZE, code={**vectors, **code})).follow({0: (0, "vector")})


def registers(*texts: str, **start) -> State:
    st = State(SEGA.reset(), **start)
    for text in texts:
        sms_registers.apply(st, text, SEGA)
    return st


def test_c_is_known_on_its_own_and_survives_b_only_changes():
    assert registers("ld b, $16", "ld c, $bf").port == 0xBF
    assert registers("ld c, $bf", "ld b, $16", "djnz $0100", "otir", "outi", "inc b").port == 0xBF
    assert registers("ld bc, $16bf").port == 0xBF and registers("ld bc, $16bf").bc == 0x16BF
    assert registers("ld a, $be", "ld c, a").port == 0xBE
    for change in ("inc c", "dec c", "ld c, (hl)", "ldir", "dec bc", "exx", "in c, ($dd)", "srl c", "set 0, c"):
        assert registers("ld c, $bf", change).port is None, change


def test_a_known_vdp_port_keeps_the_mapping_and_memory_control_still_does_not():
    vdp = found(TO_BANK5 + "0616" "0ebf" "edb3" "cd0080" "18fe")  # ld b,$16 · ld c,$bf · otir · call $8000
    assert vdp.starts.get(0x14000) == (0x8000, "call") and 0 not in vdp.unresolved
    control = found(TO_BANK5 + "0e3e" "ed79" "cd0080" "18fe")  # ld c,$3e · out (c),a
    assert 0x14000 not in control.starts
    assert "explicit memory or source-control write is unqualified" in control.unresolved[0]
    assert sms_effects.port_may_change_source("otir", registers("ld c, $bf").port) is False


UNRESOLVED = "d33e" "c9"  # out ($3e),a · ret: its effects on the bus stay unresolved


def test_the_continuation_after_an_unresolved_call_keeps_only_its_own_window():
    # at $0500 (slot 0 past its fixed first KiB): call $0200 (unresolved) · call $1000 (slot 0, the caller's own
    # window, bank 0 since its bytes run there) · call $8000 (slot 2: unknown after the call)
    result = found(TO_BANK5 + "cd0002" "cd0010" "cd0080" "18fe", at=0x0500, x0200=UNRESOLVED, x1000="3e02c9")
    assert result.starts.get(0x1000) == (0x1000, "call")
    assert 0x14000 not in result.starts and 0x8000 not in result.starts
    assert "callee has unqualified memory or source-control writes" in result.unresolved[0]
    # in the fixed first KiB, only that KiB is the caller's own: slot 0's paged part stays unknown
    fixed = found(TO_BANK5 + "cd0002" "cd0010" "18fe", x0200=UNRESOLVED, x1000="3e02c9")
    assert 0x1000 not in fixed.starts


def test_a_block_copy_into_work_ram_is_a_ram_write():
    assert sms_effects.memory_writes("ldir", {"de": 0xC100, "bc": 0x10}) == (sms_effects.Write(0xC100, None, 0x10),)
    assert sms_effects.memory_writes("lddr", {"de": 0xC10F, "bc": 0x10}) == (sms_effects.Write(0xC100, None, 0x10),)
    for de, count, text in ((0xDFF8, 0x10, "ldir"), (0xBFF8, 0x10, "ldir"), (0xC004, 0x10, "lddr"), (0xE000, 1, "ldir"),
                            (None, 0x10, "ldir"), (0xC100, None, "ldir"), (0xC100, 0, "ldir")):
        assert sms_effects.memory_writes(text, {"de": de, "bc": count}) == (sms_effects.Write(None),) * 2, (de, count)
    # ld de,$c100 · ld hl,$0400 · ld bc,$0010 · ldir · call $8000: bank 5 still mapped
    kept = found(TO_BANK5 + "1100c1" "210004" "011000" "edb0" "cd0080" "18fe")
    assert kept.starts.get(0x14000) == (0x8000, "call") and 0 not in kept.unresolved
    # ld de,$dff8 · ...: the copy runs into the RAM mirror, so it's an unknown store again
    lost = found(TO_BANK5 + "11f8df" "210004" "011000" "edb0" "cd0080" "18fe")
    assert 0x14000 not in lost.starts and "explicit memory or source-control write is unqualified" in lost.unresolved[0]


def test_a_block_copy_over_the_tracked_stack_stops_interpretation():
    st = State(SEGA.reset(), sp=0xC108, stack_top=0xC110)
    writes = sms_effects.memory_writes("ldir", {"de": 0xC100, "bc": 0x10})
    assert sms_calls.sms_stack.write_alias(st, writes) == "memory write aliases an active physical stack value"
    assert sms_calls.sms_stack.write_alias(st, sms_effects.memory_writes("ldir", {"de": 0xC000, "bc": 0x10})) is None


def test_the_same_call_from_the_same_facts_is_evaluated_once():
    rom = make_rom(size=SIZE, code={0x0200: bytes.fromhex("3e01c9")})
    evaluator = sms_calls.Evaluator(rom, SEGA, budget=sms_calls.Budget())
    caller = State(SEGA.reset())
    first = evaluator.evaluate(0x0200, caller, 0x0103)
    used = evaluator.budget.call_instructions
    assert evaluator.evaluate(0x0200, caller, 0x0103) is first and evaluator.budget.call_instructions == used
    other = evaluator.evaluate(0x0200, caller, 0x0106)  # (another return address: another evaluation)
    assert other is not first and evaluator.budget.call_instructions > used
