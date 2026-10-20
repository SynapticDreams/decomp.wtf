"""Operands after a call, found from the callee's evaluated returns (rom/sms_calls.py, rom/sms_trace.py): a routine
that pops its return address, reads bytes through it and returns past them comes back the same distance past every
evaluated call. Only an agreed, nonzero, bounded distance with no other unresolved effect becomes operands; a declared
`operands` correction still takes precedence, and conditional calls stay unqualified."""

from __future__ import annotations

from decompnet.rom import sms, sms_trace
from decompnet.rom.sms_state import Found

from .test_sms import make_rom

ONE = "e1" "7e" "23" "e5" "c9"  # pop hl · ld a,(hl) · inc hl · push hl · ret: one byte after its call
TWO = "e1" "5e" "23" "56" "23" "e5" "c9"  # pop hl · ld e,(hl) · inc hl · ld d,(hl) · inc hl · push hl · ret
LEAF = {0x0300: bytes.fromhex("3e01c9")}  # ld a,1 · ret


def rom(main: str, **routines: str) -> bytes:
    vectors = {at: b"\xc9" for at in sms.VECTORS if at}
    code = {0x0000: bytes.fromhex("c30001"), 0x0100: bytes.fromhex(main), **LEAF}
    code.update({int(at[1:], 16): bytes.fromhex(body) for at, body in routines.items()})
    return make_rom(size=0x8000, code={**vectors, **code})


def split(image: bytes, hints: dict | None = None):
    report: dict = {}
    functions = {f.rom: f for f in sms.functions(image, report=report, hints=hints)}
    return functions, report


def test_operands_every_call_returns_past_are_listed_as_bytes_and_code_resumes_after_them():
    # call $0200 · db $c3,$ff · call $0300 · call $0200 · db $12,$34 · jr $   (c3 ff would decode as a jp)
    functions, report = split(rom("cd0002" "c3ff" "cd0003" "cd0002" "1234" "18fe", x0200=TWO))
    assert report["inline_inferred"] == [{"rom_offset": 0x0200, "count": 2}]
    main = functions[0x0100]
    assert "db $c3, $ff" in main.asm and "0105  call $0300" in main.asm and "db $12, $34" in main.asm
    assert 0x0300 in functions
    assert (0x0103, 2, "inline", "read by the routine called just before: each evaluated call returned past them") \
        in report["regions"]
    assert not any(row["rom_offset"] in (0, 0x0100) for row in report["analysis_unresolved"])


def test_a_single_operand_byte_after_an_rst_is_found_the_same_way():
    functions, report = split(rom("e7" "05" "cd0003" "18fe", x0020=ONE))  # rst $20 · db 5 · call $0300
    assert report["inline_inferred"] == [{"rom_offset": 0x0020, "count": 1}]
    assert "db $05" in functions[0x0100].asm and 0x0300 in functions


def test_calls_that_disagree_keep_the_routine_unqualified():
    found = Found(returned_past={0x0200: {0, 1}, 0x0300: {1, 2}, 0x0400: {0}, 0x0500: {3}})
    assert sms_trace.inferred_inline(found) == {0x0500: 3}


def test_an_unknown_path_through_the_callee_stays_unresolved():
    maybe = "e1" "b7" "2801" "23" "e5" "c9"
    found = sms_trace.Tracer(rom("cd0002" "05" "18fe", x0200=maybe)).follow({0: (0, "vector")})  # A unknown here
    assert 0x0200 not in found.returned_past
    assert "callee changes or loses the return continuation" in found.unresolved[0]


def test_a_conditional_call_is_never_given_operands():
    found = sms_trace.Tracer(rom("c40002" "05" "18fe", x0200=ONE)).follow({0: (0, "vector")})  # call nz,$0200
    assert sms_trace.inferred_inline(found) == {}
    assert "conditional inline continuation is unqualified" in found.unresolved[0]


def test_a_declared_operands_correction_takes_precedence():
    functions, report = split(rom("cd0002" "0506" "18fe", x0200=ONE), hints={"inline": {0x0200: 2}})
    assert report["inline_inferred"] == []
    assert "db $05, $06" in functions[0x0100].asm
    assert (0x0103, 2, "inline", "read by the routine called just before") in report["regions"]


def test_operands_a_callee_reads_inside_another_callee_resume_its_evaluation():
    # main: call $0400 · call $0300 · jr $   ($0400: call $0200 · db 5 · ld a,2 · ret)
    found = sms_trace.Tracer(rom("cd0004" "cd0003" "18fe", x0200=ONE, x0400="cd0002" "05" "3e02" "c9")).follow(
        {0: (0, "vector")})
    assert 0 not in found.unresolved and 0x0400 not in found.unresolved
    assert sms_trace.inferred_inline(found) == {0x0200: 1}
    assert 0x0300 in found.starts


def test_a_return_further_than_the_operand_bound_stays_unresolved():
    far = "e1" "112800" "19" "e5" "c9"  # pop hl · ld de,40 · add hl,de · push hl · ret
    found = sms_trace.Tracer(rom("cd0002" "18fe", x0200=far)).follow({0: (0, "vector")})
    assert sms_trace.inferred_inline(found) == {}
    assert "callee changes or loses the return continuation" in found.unresolved[0]
