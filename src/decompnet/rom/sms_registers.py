"""Path-local register and dispatch-bound facts, separate from traversal and explicit memory writes."""
from __future__ import annotations

import re

from . import sms_effects
from .sms_mapping import Mapper, wram_address
from .sms_state import State

_LD_A_N = re.compile(r"^ld a, \$([0-9a-f]{2})$")
_LD_A_MEM = re.compile(r"^ld a, \(\$([0-9a-f]{4})\)$")
_LD_RR_NN = re.compile(r"^ld (hl|de|bc), \$([0-9a-f]{4})$")
_CP_N = re.compile(r"^cp \$([0-9a-f]{2})$")
_AND_N = re.compile(r"^and \$([0-9a-f]{2})$")
_SUB_N = re.compile(r"^sub \$([0-9a-f]{2})$")
# what changes A's value (so an index bounded before isn't any more): not `or a`/`and a` (tests), not doubling it
_CHANGES_A = re.compile(r"^(?:add a, (?!a$)|adc a,|sub |sbc a,|inc a$|dec a$|neg|cpl|or (?!a$)|xor |and (?!a$)|rra|"
                        r"rla|rrca|rrd|rld|srl a|sra a|rr a|rl a|rrc a|daa|ld a,|in a,|pop af|ex af)")
_WRITES_DE = re.compile(r"^(?:ld de,|ld d,|ld e,|pop de|exx|inc de|dec de|inc d$|dec d$|inc e$|dec e$|ldi|ldd|ldir|"
                        r"lddr|ex de, hl|in [de],|(?:rlc|rrc|rl|rr|sla|sra|sll|srl) [de]$|(?:res|set) \d, [de]$)")
_WRITES_BC = re.compile(r"^(?:ld bc,|ld b,|ld c,|pop bc|exx|inc bc|dec bc|inc b$|dec b$|inc c$|dec c$|djnz|ldi|ldd|"
                        r"ldir|lddr|cpi|cpd|cpir|cpdr|ini|ind|inir|indr|outi|outd|otir|otdr|in [bc],|"
                        r"(?:rlc|rrc|rl|rr|sla|sra|sll|srl) [bc]$|(?:res|set) \d, [bc]$)")
# what else changes A or HL (so what was known about them isn't any more)
_WRITES_A = re.compile(r"^(?:ld a,|in a,|inc a$|dec a$|add a,|adc a,|sub |sbc a,|and |xor |or |rlca|rrca|rla|rra|"
                       r"cpl|neg|daa|rrd|rld|pop af|ex af|rlc a|rrc a|rl a|rr a|sla a|sra a|sll a|srl a|res \d, a|set \d, a)")
_WRITES_HL = re.compile(r"^(?:ld hl,|ld h,|ld l,|pop hl|ex de, hl|exx|add hl,|adc hl,|sbc hl,|ex \(sp\), hl|inc h$|"
                        r"dec h$|inc l$|dec l$|ldi|ldd|ldir|lddr|cpi|cpd|cpir|cpdr|ini|ind|inir|indr|outi|outd|otir|otdr|"
                        r"in [hl],|(?:rlc|rrc|rl|rr|sla|sra|sll|srl) [hl]$|(?:res|set) \d, [hl]$)")


def apply(st: State, text: str, model: Mapper) -> None:
    """What an instruction does to what's known about A, HL, DE, BC, the stack and the flags."""
    if m := _CP_N.match(text):
        st.cmp = (st.n, int(m.group(1), 16) or None)
    elif (m := _AND_N.match(text)) and ((v := int(m.group(1), 16)) + 1) & v == 0 and v:
        st.bound = (st.n, v + 1, False)  # `and 7`: one of 8 at most (a table may be shorter)
    elif (m := _SUB_N.match(text)) and (b := st.fresh(st.bound)) and b[1] and (lo := st.fresh(st.low)) is not None \
            and lo >= int(m.group(1), 16):
        k = int(m.group(1), 16)  # `cp 3 / jr c / cp 8 / jr nc / sub 3`: one of 5
        st.bound, st.low = (st.n, b[0] - k, True), (st.n, lo - k)
    elif _CHANGES_A.match(text):
        st.bound = st.low = None
    elif re.match(r"^ld [bcdehl], a$", text) and (b := st.fresh(st.bound)):
        st.index = (st.n, *b)  # the index goes on in another register: what A does next doesn't change it
    if text == "pop af":
        st.a = st.stack.pop() if st.stack else None
        return
    if text in ("pop hl", "pop de", "pop bc"):
        val = st.stack.pop() if st.stack else None
        reg = text[4:]
        st.hl, st.de, st.bc = (val if reg == "hl" else st.hl, val if reg == "de" else st.de,
                               val if reg == "bc" else st.bc)
        return
    if text == "ex de, hl":
        st.de, st.hl = st.hl, st.de
        return
    if text in ("pop ix", "pop iy"):
        if st.stack:
            st.stack.pop()
        return
    if text.startswith("ld sp, ") or text in ("inc sp", "dec sp"):
        st.stack.clear()
    if m := _LD_A_N.match(text):
        st.a = int(m.group(1), 16)
    elif text == "xor a":
        st.a = 0
    elif m := _LD_A_MEM.match(text):
        addr = int(m.group(1), 16)
        st.a = st.mem.get(wram_address(addr)) if model.resolve(addr, st.mapping).space == "wram" else None
    elif text == "ld a, (hl)" and st.hl is not None and st.hl >= 0xC000:
        st.a = st.mem.get(wram_address(st.hl)) if model.resolve(st.hl, st.mapping).space == "wram" else None
    elif _WRITES_A.match(text):
        st.a = None
    if m := _LD_RR_NN.match(text):
        value = int(m.group(2), 16)
        setattr(st, m.group(1), value)
        if 0x0100 <= value < 0xC000:
            st.base = (st.n, value)
    else:
        if text == "inc hl" and st.hl is not None:
            st.hl = (st.hl + 1) & 0xFFFF
        elif text == "dec hl" and st.hl is not None:
            st.hl = (st.hl - 1) & 0xFFFF
        elif _WRITES_HL.match(text):
            st.hl = None
        if _WRITES_DE.match(text):
            st.de = None
        if _WRITES_BC.match(text):
            st.bc = None
    if copied := sms_effects.copied_register(text):
        pair = {"b": "bc", "c": "bc", "d": "de", "e": "de", "h": "hl", "l": "hl"}.get(copied, "a")
        setattr(st, pair, None)
        st.cmp = st.low = st.bound = st.index = st.base = None
