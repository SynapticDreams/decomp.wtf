"""Machine code no compiler makes: functions written in assembly, which no C or C++ source compiles to.

decomp.wtf matches functions from C/C++ only (an asm function would "match" anything), so a function like this is
taken out of agents' way before they spend their turns on it. Only a certain sign counts, since a C function taken
for assembly would never be worked on.

PowerPC (GameCube, Wii): its first instructions, up to the first branch, read r0, r11 or r12 before setting them.
Compiled code receives its arguments in r3-r10 and f1-f8 and never reads a scratch register it hasn't set;
CodeWarrior's runtime helpers take theirs there: __ptmf_scall and its kin the pointer-to-member in r12, __save_gpr
the save area in r11 (Mario Party 6's minigame modules each link their own copies).

Not a sign: instructions only assembly has (mtmsr, mtspr of a GQR...). C functions get them too, inlined from the
SDK's headers (OSInitFastCast's asm block, in HuSysInit), and an agent matches those by calling the same helpers.

MIPS (N64, PlayStation, PlayStation 2), see mips_reason: coprocessor 0 (the system: mfc0, mtc0, rfe, eret) or, on
the PlayStations, coprocessor 2 (the PS1's GTE, the PS2's VU0: ctc2, mtc2, lwc2, cop2 commands), which C compilers
never emit (PSY-Q's libgte is written in assembly; C that drives the GTE does it with inline asm, which decomp.wtf
doesn't take); code that ends without a return or a jump and so runs on into the next function (an extra entry
point into hand-written code: the splitter cut it off); or a first block that reads a temporary register (at, v0,
v1, t0-t9) or k0/k1 before setting it (compiled code gets its arguments in a0-a3).

SM83 (Game Boy, Game Boy Color), see sm83_reason. The split of a Game Boy ROM bounds each function by the next
called address, so what it hands out isn't always a function: padding (00/FF bytes only), a stretch that runs 1 KiB
without reaching the next function (graphics and tables after the last routine), bytes that are no instruction, or
ones SDCC never writes (ld b, b: a register to itself; rst $38, an FF byte). SDCC can't write any of those. Of real code: a routine that runs on into the next one (it ends without a return or
a jump: hand-written code that shares its tail), one that reads the carry or zero flag before setting it (C passes
nothing in the flags), one that sets the stack pointer to an address (start-up code), or one with halt or stop (C
writes those only as inline assembly, which decomp.wtf doesn't take).
"""

from __future__ import annotations

import re

_SCRATCH = (0, 11, 12)  # never an argument, never read by compiled code before it's set

# What instructions do with general registers, for the first block: opcode 31's extended opcodes by form
_X_LOAD = {23, 55, 87, 119, 279, 311, 343, 375, 534, 790, 20}  # lwzx..lhaux, lwbrx, lhbrx, lwarx: rD <- (rA|0 + rB)
_X_FLOAD = {535, 567, 599, 631}  # lfsx..lfdux: an FPR <- (rA|0 + rB)
_X_STORE = {151, 183, 215, 247, 407, 439, 662, 918, 150}  # stwx..sthux, stwbrx, sthbrx, stwcx.: rS -> (rA|0 + rB)
_X_FSTORE = {663, 695, 727, 759, 983}  # stfsx..stfdux, stfiwx: an FPR -> (rA|0 + rB)
_X_UPDATE = {55, 119, 311, 375, 567, 631, 183, 247, 439, 695, 759}  # the ...ux forms: rA is read and written
_XO_ARITH = {266, 10, 138, 234, 202, 40, 8, 136, 232, 200, 104, 235, 75, 11, 491, 459}  # rD <- rA (op rB)
_XO_ONE = {234, 202, 232, 200, 104}  # addme, addze, subfme, subfze, neg: rA only
_X_LOGIC = {28, 60, 444, 124, 316, 284, 412, 476, 24, 536, 792}  # and..sraw: rA <- rS op rB
_X_LOGIC1 = {824, 26, 922, 954}  # srawi, cntlzw, extsh, extsb: rA <- rS
_X_CACHE = {86, 54, 470, 278, 246, 1014, 982}  # dcbf, dcbst, dcbi, dcbt, dcbtst, dcbz, icbi: (rA|0 + rB)
_X_NEUTRAL = {598, 854, 512, 19}  # sync, eieio, mcrxr, mfcr (writes a GPR: see below)


def _words(code: bytes):
    for at in range(0, len(code) - 3, 4):
        yield int.from_bytes(code[at:at + 4], "big")


def _uses(w: int) -> tuple[list[int], list[int]] | None:
    """(general registers read, written) by one instruction of a function's first block; None at a branch (the
    block ends) or an instruction not known here (no verdict)."""
    op, d, a, b = w >> 26, (w >> 21) & 31, (w >> 16) & 31, (w >> 11) & 31
    base = [a] if a else []  # (rA|0): r0 there means the number 0
    if op in (14, 15):  # addi, addis (li, lis)
        return base, [d]
    if op in (7, 8, 12, 13):  # mulli, subfic, addic, addic.
        return [a], [d]
    if op in (10, 11, 3):  # cmpli, cmpi, twi
        return [a], []
    if op in (24, 25, 26, 27, 28, 29):  # ori..andis.: rA <- rS op imm
        if op == 24 and w & 0xFFFF == 0 and a == d:  # nop (ori r0,r0,0), and ori rX,rX,0
            return [], []
        return [d], [a]
    if op in (20, 21, 23):  # rlwimi (inserts into rA), rlwinm, rlwnm (shifts by rB)
        return [d] + ([a] if op == 20 else []) + ([b] if op == 23 else []), [a]
    if 32 <= op <= 47:  # integer loads and stores
        if op == 46:  # lmw rD..r31
            return base, list(range(d, 32))
        if op == 47:  # stmw rS..r31
            return list(range(d, 32)) + base, []
        update = bool(op & 1)
        addr = [a] if update else base
        if op in (36, 37, 38, 39, 44, 45):  # stores
            return [d] + addr, [a] if update else []
        return addr, [d] + ([a] if update else [])
    if 48 <= op <= 55 or op in (56, 57, 60, 61):  # float loads and stores, psq_l(u)/psq_st(u): rA only
        update = bool(op & 1)
        return ([a] if update else base), ([a] if update else [])
    if op == 4:  # paired singles; psq_lx/psq_stx(u) take rA and rB
        xo = (w >> 1) & 0x3F
        if xo in (6, 7, 38, 39):
            return ([a] if xo >= 32 else base) + [b], [a] if xo >= 32 else []
        return [], []
    if op in (59, 63):  # floating point arithmetic
        return [], []
    if op == 31:
        xo = (w >> 1) & 0x3FF
        if xo in _X_LOAD or xo in _X_FLOAD:
            upd = xo in _X_UPDATE
            return ([a] if upd else base) + [b], ([d] if xo in _X_LOAD else []) + ([a] if upd else [])
        if xo in _X_STORE or xo in _X_FSTORE:
            upd = xo in _X_UPDATE
            return ([d] if xo in _X_STORE else []) + ([a] if upd else base) + [b], [a] if upd else []
        if (w >> 1) & 0x1FF in _XO_ARITH:  # (also with OE set)
            return [a] + ([] if (w >> 1) & 0x1FF in _XO_ONE else [b]), [d]
        if xo in _X_LOGIC:
            if xo == 444 and d == b == a:  # mr rX,rX
                return [], []
            return [d, b], [a]
        if xo in _X_LOGIC1:
            return [d], [a]
        if xo in (0, 32, 4):  # cmp, cmpl, tw
            return [a, b], []
        if xo == 339:  # mfspr
            return [], [d]
        if xo in (467, 144):  # mtspr, mtcrf
            return [d], []
        if xo in _X_CACHE:
            return base + [b], []
        if xo in _X_NEUTRAL:
            return [], [d] if xo == 19 else []
        return None
    if op == 19:  # cr logic, mcrf and isync go on; bclr/bcctr and the rest end the block
        return ([], []) if (w >> 1) & 0x3FF in (0, 33, 129, 150, 193, 225, 257, 289, 417, 449) else None
    return None  # branches (b, bc), sc, a zero word, data...: the end of the block


def ppc_reason(code: bytes) -> str | None:
    """Why this PowerPC function (its big-endian code, from the entry) can't come from a compiler, or None."""
    written: set[int] = set()
    for w in _words(code):
        uses = _uses(w)
        if uses is None:
            return None
        reads, writes = uses
        for r in reads:
            if r in _SCRATCH and r not in written:
                return f"reads r{r} before setting it: compiled code receives nothing there"
        written.update(writes)
    return None


_MIPS_TEMPS = {1, 2, 3, 8, 9, 10, 11, 12, 13, 14, 15, 24, 25, 26, 27}  # at, v0-v1, t0-t7, t8-t9, k0-k1
_MIPS_LOAD = set(range(0x20, 0x28)) | {0x37, 0x1A, 0x1B, 0x1E}  # lb..lwr, ld, ldl/ldr, lq (EE)
_MIPS_STORE = set(range(0x28, 0x2F)) | {0x3F, 0x2C, 0x2D, 0x1F}  # sb..swr, sd, sdl/sdr, sq (EE)


def _mips_transfer(w: int) -> bool:
    """An unconditional transfer a function can end with: jr/jalr, j/jal, b (beq zero, zero), bal."""
    op = w >> 26
    if op == 0:
        return (w & 0x3F) in (8, 9)
    if op in (2, 3):
        return True
    if op == 4 and (w >> 21) & 31 == 0 and (w >> 16) & 31 == 0:
        return True
    return op == 1 and (w >> 21) & 31 == 0 and (w >> 16) & 31 in (1, 17)  # bgez/bgezal zero


def _mips_branch(w: int) -> bool:
    op = w >> 26
    return _mips_transfer(w) or op in (1, 4, 5, 6, 7, 0x14, 0x15, 0x16, 0x17) or (op in (0x11, 0x12) and (w >> 21) & 31 == 8)


def _mips_uses(w: int) -> tuple[set[int], set[int]] | None:
    """(general registers read, written) by one MIPS instruction, None when not known (no verdict)."""
    op, rs, rt, rd = w >> 26, (w >> 21) & 31, (w >> 16) & 31, (w >> 11) & 31
    if op == 0:
        f = w & 0x3F
        if f in (0, 2, 3):  # sll, srl, sra (sll zero = nop)
            return ({rt}, {rd})
        if f in (4, 6, 7, 0x14, 0x16, 0x17):  # sllv, srlv, srav, dsllv...
            return ({rs, rt}, {rd})
        if f in (0x38, 0x3A, 0x3B, 0x3C, 0x3E, 0x3F):  # dsll, dsrl, dsra, dsll32...
            return ({rt}, {rd})
        if f == 8:
            return ({rs}, set())
        if f == 9:
            return ({rs}, {rd})
        if f in (0x10, 0x12):  # mfhi, mflo
            return (set(), {rd})
        if f in (0x11, 0x13):  # mthi, mtlo
            return ({rs}, set())
        if f in (0x18, 0x19, 0x1A, 0x1B, 0x1C, 0x1D, 0x1E, 0x1F):  # mult, multu, div, divu (and doubleword)
            return ({rs, rt}, set())
        if 0x20 <= f <= 0x2F:  # add..sltu, dadd..
            return ({rs, rt}, {rd})
        if f in (0x0C, 0x0D, 0x0F):  # syscall, break, sync
            return (set(), set())
        if 0x30 <= f <= 0x36:  # traps
            return ({rs, rt}, set())
        return None
    if op in (8, 9, 10, 11, 12, 13, 14, 0x18, 0x19):  # addi(u), slti(u), andi, ori, xori, daddi(u)
        return ({rs}, {rt})
    if op == 15:  # lui
        return (set(), {rt})
    if op in _MIPS_LOAD:
        return ({rs}, {rt})
    if op in _MIPS_STORE:
        return ({rs, rt}, set())
    if op in (0x31, 0x35, 0x39, 0x3D):  # lwc1, ldc1, swc1, sdc1: the base register
        return ({rs}, set())
    if op == 0x11:  # FPU: mfc1/dmfc1/cfc1 write a GPR, mtc1/dmtc1/ctc1 read one, the rest none
        return ((set(), {rt}) if rs in (0, 1, 2) else ({rt}, set()) if rs in (4, 5, 6) else (set(), set()))
    if op in (4, 5, 0x14, 0x15):  # beq, bne (likely)
        return ({rs, rt}, set())
    if op in (1, 6, 7, 0x16, 0x17):  # bgez/bltz..., blez, bgtz (likely)
        return ({rs}, set())
    if op in (2, 3):
        return (set(), {31} if op == 3 else set())
    return None


def mips_reason(code: bytes, big_endian: bool, platform: str = "") -> str | None:
    """Why this MIPS function (its code, from the entry) can't come from a compiler, or None."""
    order = "big" if big_endian else "little"
    words = [int.from_bytes(code[at:at + 4], order) for at in range(0, len(code) - 3, 4)]
    if not words:
        return None
    for w in words:
        op = w >> 26
        if op == 0x10:
            return "uses coprocessor 0 (the system's: mfc0, mtc0, rfe, eret): no C compiler emits it"
        if platform in ("psx", "ps", "ps2") and (op == 0x12 or op in (0x32, 0x3A, 0x36, 0x3E)):
            unit = "the GTE (coprocessor 2)" if platform != "ps2" else "VU0 (coprocessor 2)"
            return (f"uses {unit}: no C compiler emits it (PSY-Q's libgte is written in assembly; C does it with "
                    "inline asm)" if platform != "ps2" else f"uses {unit}: C reaches it only through inline asm")
    body = list(words)
    while len(body) > 1 and body[-1] == 0:  # alignment padding
        body.pop()
    if not any(_mips_transfer(w) for w in body[-2:]):
        return ("ends without a return or a jump, so it runs on into the next function: an entry point inside "
                "hand-written code (compiled functions end with jr ra)")
    names = {1: "at", 2: "v0", 3: "v1", 24: "t8", 25: "t9", 26: "k0", 27: "k1"}
    # the PS2's EABI passes eight integer arguments: a0-a3 and t0-t3
    temps = _MIPS_TEMPS - {8, 9, 10, 11} if platform == "ps2" else _MIPS_TEMPS
    args = "a0-a3 and t0-t3" if platform == "ps2" else "a0-a3"
    written: set[int] = {0}
    for i, w in enumerate(words[:64]):
        uses = _mips_uses(w)
        if uses is None:
            return None
        if (early := sorted((uses[0] - written) & temps)):
            name = names.get(early[0], f"t{early[0] - 8}")
            return f"reads {name} before setting it: compiled code gets its arguments in {args}"
        written |= uses[1]
        if _mips_branch(w) and i + 1 < len(words):  # the first block ends with the branch's delay slot
            slot = _mips_uses(words[i + 1])
            if slot is not None and (early := sorted((slot[0] - written) & temps)):
                name = names.get(early[0], f"t{early[0] - 8}")
                return f"reads {name} before setting it: compiled code gets its arguments in {args}"
            return None
    return None


# ------------------------------------------------------------------------------------------------ SM83

_SM83_UNDEFINED = {0xD3, 0xDB, 0xDD, 0xE3, 0xE4, 0xEB, 0xEC, 0xED, 0xF4, 0xFC, 0xFD}  # no instruction has them
_SM83_COND = re.compile(r"^(jr|jp|call|ret) (n?[zc]),?")  # a branch on a flag
_SM83_ZC = re.compile(r"^(add a|adc|sub|sbc|and|xor|or|cp|daa|rlca|rrca|rla|rra|rlc|rrc|rl |rr |sla|sra|srl|swap)\b")
_SM83_Z = re.compile(r"^((inc|dec) ([abcdehl]|\[hl\])|bit )")  # sets the zero flag, not the carry
_SM83_C = re.compile(r"^(scf|add hl|add sp|ld hl, sp)")  # sets the carry, not the zero flag
_SM83_READS_C = re.compile(r"^(adc|sbc|rla|rra|rl |rr |ccf)\b")
_SM83_BRANCH = re.compile(r"^(jr|jp|call|ret|reti|rst)\b")
_SM83_SELF_MOVE = re.compile(r"^ld ([abcdehl]), \1$")  # ld b, b: a register to itself (0x40 0x49 ... bytes)


def sm83_reason(code: bytes, base: int = 0, capped: bool = False) -> str | None:
    """Why this Game Boy function (its code, from the entry at `base`) isn't code SDCC compiled, or None.
    `capped`: the split gave it its longest size, not having found the next function."""
    from .rom import sm83

    if not code:
        return None
    if all(b in (0x00, 0xFF) for b in code):
        return "padding (00 or FF bytes only), not a function"
    if capped:
        return "the split ran 1 KiB without reaching the next function: its end isn't known (data follows code)"
    insns, off = [], 0
    for addr, text, ln in sm83.disassemble(code, base):
        if text.startswith("db $") and code[off] in _SM83_UNDEFINED:
            return f"bytes that are no instruction (at ${addr:04x}): data, not code"
        if _SM83_SELF_MOVE.match(text) or text == "rst $38":  # no compiler writes these: bytes of graphics do
            return f"{text} at ${addr:04x}, which SDCC never writes: data, not code"
        insns.append((addr, text, ln))
        off += max(1, ln)
    addr, last, ln = insns[-1]
    ends = last in ("ret", "reti", "jp hl") or re.match(r"^(jp|jr) \$", last) is not None
    if not ends or addr + ln > base + len(code):
        return "runs on into the next function (it ends without a return or a jump): hand-written"
    z = c = False
    for addr, text, ln in insns:
        cond = _SM83_COND.match(text)
        if cond and ((cond.group(2)[-1] == "z" and not z) or (cond.group(2)[-1] == "c" and not c)) \
                or (_SM83_READS_C.match(text) and not c):
            flag = "zero" if cond and cond.group(2)[-1] == "z" else "carry"
            return f"reads the {flag} flag before setting it ({text}): C passes nothing in the flags"
        if _SM83_BRANCH.match(text):
            break
        if _SM83_ZC.match(text):
            z = c = True
        elif _SM83_Z.match(text):
            z = True
        elif _SM83_C.match(text):
            c = True
    for addr, text, ln in insns:
        if text.startswith("ld sp, $"):
            return "sets the stack pointer to an address: start-up code, hand-written"
        if text == "halt" or text.startswith("stop"):
            return f"{text.split()[0]} at ${addr:04x}: C writes it only as inline assembly, which isn't taken"
    return None


def sm83_routine(code: bytes, base: int = 0) -> int | None:
    """How long the routine at the start of a Game Boy function is, when the split ran it on into what follows
    (padding, data, or code with no entry of its own): up to its first return or jump that no earlier branch goes
    past, if that's code SDCC could have written (sm83_reason). None: no such end before the function's own."""
    from .rom import sm83

    far, off = base, 0
    for addr, text, ln in sm83.disassemble(code, base):
        if text.startswith("db $"):
            return None
        if (m := re.match(r"^(jr|jp)\b.*\$([0-9a-f]{4})$", text)):
            far = max(far, int(m.group(2), 16))  # a branch inside: the routine goes on at least that far
        off += max(1, ln)
        if (text in ("ret", "reti") or re.match(r"^(jp|jr) \$", text)) and far < addr + ln:
            return off if off < len(code) and sm83_reason(code[:off], base) is None else None
    return None
