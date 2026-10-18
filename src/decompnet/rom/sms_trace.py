"""Following a Master System / Game Gear game's code with the banks it maps, to find its functions and the CPU address
each runs at.

The Sega mapper shows 16 KiB banks of the ROM in three slots (0x0000, 0x4000, 0x8000) and code picks the banks of
slots 1 and 2 by writing their number to 0xFFFE and 0xFFFF. Which bank a call to 0x8123 reaches, and where a bank's
code runs, isn't in the ROM's layout: it's in the code. So the code is followed from the reset, interrupt and pause
entry points, instruction by instruction, keeping track of what's in each slot:

- `ld a,5 / ld ($ffff),a` (and through HL: `ld hl,$ffff / ld (hl),5`) maps a bank; the mapper reads only as many
  bits as the ROM needs;
- a function that writes the A it was called with to the mapper maps the bank its callers pass in A;
- a jump or call into the slot the code runs from stays in its own bank;
- a function that never returns (a main loop, a reset) or that takes its return address to read a table that
  follows its call (`call dispatch / .dw a, b, c`) ends the straight-line code at the call.

Rounds repeat that with what the last one learned (functions that don't return, bank switchers) until nothing
changes. Code tables a game reads through a dispatcher (`ld hl,table / rst $20`) and labels from a WLA-DX symbol file
next to the ROM (emulators and disassemblers write them) seed more functions.
(Ideas from another fork of the original, rewritten for this lane's own disassembler and records.)
"""

from __future__ import annotations

import bisect
import re
from dataclasses import dataclass, field

from . import z80

BANK = 0x4000
VECTORS = (0x0000, 0x0008, 0x0010, 0x0018, 0x0020, 0x0028, 0x0030, 0x0038, 0x0066)
ARG = "arg"  # A as the function was entered with it: a function that maps it is a bank switcher

_LD_A_N = re.compile(r"^ld a, \$([0-9a-f]{2})$")
_LD_A_MEM = re.compile(r"^ld a, \(\$([0-9a-f]{4})\)$")
_LD_MEM_A = re.compile(r"^ld \(\$([0-9a-f]{4})\), a$")
_LD_HL_NN = re.compile(r"^ld hl, \$([0-9a-f]{4})$")
_LD_HLP_N = re.compile(r"^ld \(hl\), \$([0-9a-f]{2})$")
# what else changes A or HL (so what was known about them isn't any more)
_WRITES_A = re.compile(r"^(?:ld a,|in a,|inc a$|dec a$|add a,|adc a,|sub |sbc a,|and |xor |or |rlca|rrca|rla|rra|"
                       r"cpl|neg|daa|pop af|ex af|rlc a|rrc a|rl a|rr a|sla a|sra a|sll a|srl a|res \d, a|set \d, a)")
_WRITES_HL = re.compile(r"^(?:ld hl,|ld h,|ld l,|pop hl|ex de, hl|exx|add hl,|adc hl,|sbc hl,|ex \(sp\), hl|inc h$|"
                        r"dec h$|inc l$|dec l$|ldi|ldd|ldir|lddr|cpi|cpd|cpir|cpdr|ini|ind|inir|indr|outi|outd|otir|otdr|"
                        r"rlc [hl]$|rrc [hl]$|rl [hl]$|rr [hl]$|sla [hl]$|sra [hl]$|srl [hl]$)")


def bank_mask(size: int) -> int:
    """The mapper reads only as many bank bits as the ROM needs (`ld a,$82 / ld ($ffff),a` maps bank 2 of 512 KiB)."""
    banks = 1
    while banks * BANK < size:
        banks <<= 1
    return banks - 1


def resolve(target: int, here_flat: int, here_cpu: int, s1, s2, size: int) -> int | None:
    """The ROM offset a call or jump to CPU address `target` reaches from code at `here_flat` (running at
    `here_cpu`) while slots 1 and 2 hold banks `s1` and `s2` (None: not known). None for RAM, an unknown bank, or
    past the ROM's end."""
    if target >= 0xC000:
        return None
    if target < 0x4000:
        return target if target < size else None
    slot = target >> 14
    if here_cpu >= 0x4000 and here_cpu >> 14 == slot:
        bank = here_flat // BANK  # into the slot the code runs from: its own bank
    else:
        bank = s1 if slot == 1 else s2
    if not isinstance(bank, int):
        return None
    flat = bank * BANK + (target & (BANK - 1))
    return flat if flat < size else None


@dataclass
class State:
    s1: object
    s2: object
    a: object = None   # an int, ARG, or None
    hl: int | None = None

    def copy(self) -> State:
        return State(self.s1, self.s2, self.a, self.hl)


@dataclass
class Found:
    starts: dict[int, tuple[int, str]] = field(default_factory=dict)  # flat -> (cpu it runs at, how it was found)
    entered: dict[int, set] = field(default_factory=dict)  # flat -> every (s1, s2) it was entered with
    returns: set[int] = field(default_factory=set)  # functions a path of which reaches a return
    takes_return: set[int] = field(default_factory=set)  # functions that pop their return address (a table follows)
    switchers: dict[int, int] = field(default_factory=dict)  # function -> the slot it maps the A it's given into
    dispatchers: set[int] = field(default_factory=set)  # functions that jump through HL to an address they read
    # calls and tail jumps made with a known address in HL: (from flat, from cpu, HL, the slots then, to flat): a
    # table, when what they go to is a dispatcher
    with_hl: list[tuple[int, int, int, tuple, int]] = field(default_factory=list)
    jumps: list[tuple[int, int, int, tuple]] = field(default_factory=list)  # (function, to flat, to cpu, slots)
    anchors: set[int] = field(default_factory=set)  # starts reached by something other than a jump (a call...)
    slot_writes: dict[int, int] = field(default_factory=dict)  # 1 | 2 -> mapper writes seen that pick that slot's bank
    bank_base: dict[int, int] = field(default_factory=dict)  # bank -> the CPU address its code was found running at


def _decode(data: bytes, flat: int, cpu: int) -> tuple[str, int]:
    end = min(len(data), (flat // BANK + 1) * BANK)
    return z80.decode(data[flat:min(end, flat + 4)], cpu)


def _agreed(mappings: set) -> tuple:
    s1 = {m[0] for m in mappings}
    s2 = {m[1] for m in mappings}
    return (s1.pop() if len(s1) == 1 else None), (s2.pop() if len(s2) == 1 else None)


def can_start(data: bytes, flat: int, cpu: int) -> bool:
    """Where a call or jump can land: an instruction, and not the $FF filler of an empty bank (`rst $38` again and
    again)."""
    if not 0 <= flat < len(data) or data[flat:flat + 2] == b"\xff\xff":
        return False
    return not _decode(data, flat, cpu)[0].startswith("db ")


_ODD_START = re.compile(r"^(?:nop|ld \(bc\), a|ld \(de\), a|ex af|halt|rst |daa|ccf|scf|di$|ei$|ld ([a-e]), \1$)")


def plausible(data: bytes, flat: int, cpu: int, limit: int = 64) -> bool:
    """For an address that's only a guess (a word in a table): code that reads like a function's start: no filler or
    undefined opcodes, not what tables of numbers decode to first, and a return or jump within `limit` instructions
    in the bank."""
    if not can_start(data, flat, cpu) or data[flat:flat + 2] == b"\x00\x00":
        return False
    for k in range(limit):
        text, ln = _decode(data, flat, cpu)
        if text.startswith("db ") or text == "rst $38" or (k == 0 and _ODD_START.match(text)):
            return False
        if z80.flow(text)[0] in ("ret", "jump"):
            return True
        flat, cpu = flat + max(1, ln), cpu + max(1, ln)
        if flat % BANK == 0:
            return False
    return False


class Tracer:
    def __init__(self, data: bytes, paged: set[int] | None = None):
        """`paged`: the slots (1, 2) the game is known to pick banks for (a first pass learns it: `slot_writes`). Code
        entered from somewhere nothing was followed from (the interrupt handlers, what a sweep found) can't know
        what those slots hold, so their bank is unknown there; a slot the game never pages keeps its power-on bank.
        None: every slot keeps its power-on bank (the first pass's view)."""
        self.data, self.size = data, len(data)
        self.mask = bank_mask(self.size)
        self.mapper = self.size > 3 * BANK  # 48 KiB or less: the ROM is simply at 0x0000-0xBFFF
        self.unknown = (None if paged and 1 in paged else 1, None if paged and 2 in paged else 2)
        self.found = Found()
        self.known: set[int] = set()  # function starts as the last round left them (and the seeds)
        self.prev_starts: set[int] = set()

    def follow(self, seeds: dict[int, tuple[int, str]], rounds: int = 8) -> Found:
        """The functions reachable from `seeds` (flat -> (cpu, why)), in rounds until nothing changes: each round
        starts again from the seeds with what the last one learned (far jumps and tables that start functions,
        functions that don't return, bank switchers). The reset vector starts with the power-on banks; any other
        seed with what its callers had mapped, as far as they agree (else `unknown`)."""
        more: dict[int, tuple[int, str]] = {}  # far jumps and tables, as the last round found them
        before = None
        for _ in range(rounds):
            todo = {**more, **seeds}
            self.known = set(todo)
            self.prev_starts = set(self.found.starts)
            self._round(todo)
            more = {**self._far_jumps(), **self._tables()}
            now = (frozenset(self.found.starts.items()), frozenset(self.found.switchers.items()),
                   frozenset(self.found.returns), frozenset(self.found.takes_return), frozenset(more))
            if now == before:
                break
            before = now
        self._bank_bases()
        return self.found

    # -- one round

    def _round(self, seeds: dict[int, tuple[int, str]]) -> None:
        f = self.found
        prev, f.entered, f.starts, f.with_hl, f.jumps, f.anchors = f.entered, {}, {}, [], [], set()
        queue = [(flat, cpu, why, (1, 2) if flat == 0 else None) for flat, (cpu, why) in sorted(seeds.items())]
        for flat, _cpu, _why, m in queue:
            if m is not None:
                f.entered.setdefault(flat, set()).add(m)
        seen: set[int] = set()
        while queue:
            flat, cpu, why, mapping = queue.pop()
            if why != "jump" and can_start(self.data, flat, cpu):
                f.anchors.add(flat)
            if flat in seen or not can_start(self.data, flat, cpu):
                continue
            seen.add(flat)
            f.starts.setdefault(flat, (cpu, why))
            # a slot's bank holds inside a function only when everything that enters it agrees on it
            entries = prev.get(flat, set()) | ({mapping} if mapping is not None else set())
            s1, s2 = (1, 2) if not self.mapper else _agreed(entries) if entries else self.unknown
            for cflat, ccpu, m, how in self._trace(flat, cpu, State(s1, s2, ARG)):
                f.entered.setdefault(cflat, set()).add(m)
                queue.append((cflat, ccpu, how, m))

    def _slot_value(self, val):
        return val & self.mask if isinstance(val, int) else None

    def _no_return(self, flat: int) -> bool:
        """A call to it doesn't come back to the next instruction (as the last round saw it)."""
        f = self.found
        return flat in f.takes_return or (flat in self.prev_starts and flat not in f.returns)

    def _trace(self, entry: int, entry_cpu: int, st: State) -> list[tuple[int, int, tuple, str]]:
        """Follow one function; returns the functions it calls or jumps to: (flat, cpu, the banks mapped then,
        "call" | "jump")."""
        f, data, size = self.found, self.data, self.size
        out: list[tuple[int, int, tuple, str]] = []
        work = [(entry, entry_cpu, st)]
        visited: set[int] = set()
        pushes = 0
        while work:
            flat, cpu, st = work.pop()
            while flat not in visited and 0 <= flat < size:
                visited.add(flat)
                text, ln = _decode(data, flat, cpu)
                if text.startswith("db "):
                    break
                kind, target = z80.flow(text)
                # the mapper
                slot_reg = None
                if (m := _LD_MEM_A.match(text)) and int(m.group(1), 16) in (0xFFFE, 0xFFFF):
                    slot_reg, val = int(m.group(1), 16), st.a
                elif text == "ld (hl), a" and st.hl in (0xFFFE, 0xFFFF):
                    slot_reg, val = st.hl, st.a
                elif (m := _LD_HLP_N.match(text)) and st.hl in (0xFFFE, 0xFFFF):
                    slot_reg, val = st.hl, int(m.group(1), 16)
                if slot_reg is not None:
                    slot = 1 if slot_reg == 0xFFFE else 2
                    if not (slot == 1 and val == 1):  # (start-up code setting the power-on bank isn't paging)
                        f.slot_writes[slot] = f.slot_writes.get(slot, 0) + 1
                    if val == ARG:
                        f.switchers.setdefault(entry, 1 if slot_reg == 0xFFFE else 2)
                    if slot_reg == 0xFFFE:
                        st.s1 = self._slot_value(val)
                    else:
                        st.s2 = self._slot_value(val)
                if text.startswith("push "):
                    pushes += 1
                if text == "pop hl" and pushes == 0 and len(visited) <= 3:
                    f.takes_return.add(entry)  # its return address, first thing: the table that follows its call
                if text in ("jp (hl)", "jp (ix)", "jp (iy)") and st.hl is None:
                    f.dispatchers.add(entry)  # to an address it worked out: a dispatcher
                if kind in ("ret", "cret") and not text.startswith("jp ("):
                    f.returns.add(entry)
                if target is not None and kind in ("call", "jump", "cjump"):
                    tflat = resolve(target, flat, cpu, st.s1, st.s2, size)
                    if tflat is not None:
                        inside = (tflat // BANK == entry // BANK and target >> 14 == cpu >> 14 and tflat != entry
                                  and tflat not in self.known)
                        if kind != "call" and tflat != entry:  # every jump: the next round sees which are far
                            f.jumps.append((entry, tflat, target, (st.s1, st.s2)))
                        if kind == "call" or not inside:
                            if tflat != entry:  # a call, or a jump to another function: a tail call
                                out.append((tflat, target, (st.s1, st.s2), "call" if kind == "call" else "jump"))
                                if st.hl is not None:
                                    f.with_hl.append((flat, cpu, st.hl, (st.s1, st.s2), tflat))
                        else:  # a branch within the function
                            work.append((tflat, target, st.copy()))
                    if kind == "call":
                        a_before = st.a
                        st.a, st.hl = None, None
                        if tflat is not None:
                            if tflat in f.switchers:
                                if f.switchers[tflat] == 1:
                                    st.s1 = self._slot_value(a_before)
                                else:
                                    st.s2 = self._slot_value(a_before)
                            if not text.startswith("call ") or "," not in text:  # (an unconditional call)
                                if self._no_return(tflat):
                                    break  # it doesn't come back here: what follows the call isn't this code
                if kind != "call":
                    if m := _LD_A_N.match(text):
                        st.a = int(m.group(1), 16)
                    elif text == "xor a":
                        st.a = 0
                    elif _WRITES_A.match(text):
                        st.a = None
                    if m := _LD_HL_NN.match(text):
                        st.hl = int(m.group(1), 16)
                    elif text == "inc hl" and st.hl is not None:
                        st.hl = (st.hl + 1) & 0xFFFF
                    elif text == "dec hl" and st.hl is not None:
                        st.hl = (st.hl - 1) & 0xFFFF
                    elif _WRITES_HL.match(text):
                        st.hl = None
                if kind in ("ret", "jump"):
                    break
                nxt = flat + max(1, ln)
                if nxt % BANK == 0:
                    break  # ran off the end of the bank
                flat, cpu = nxt, cpu + max(1, ln)
        return out

    # -- what a round teaches the next

    def _far_jumps(self) -> dict[int, tuple[int, str]]:
        """Jump targets that are functions of their own: outside the jumping function's own bytes (its start up to
        the next function in the bank that something calls), or jumped to from more than one function (a shared
        tail, a dispatcher). Worked out afresh each round from every jump, so a guess an earlier round made from
        code it took for another function's doesn't stay."""
        f = self.found
        anchors = sorted(f.anchors | set(f.starts) - {t for _e, t, _c, _m in f.jumps})
        jumpers: dict[int, set] = {}
        for entry, tflat, _tcpu, _m in f.jumps:
            jumpers.setdefault(tflat, set()).add(entry)
        out = {}
        for entry, tflat, tcpu, _m in f.jumps:
            k = bisect.bisect_right(anchors, entry)
            end = min(anchors[k] if k < len(anchors) else self.size, (entry // BANK + 1) * BANK)
            if not entry <= tflat < end or len(jumpers[tflat]) > 1:
                out.setdefault(tflat, (tcpu, "jump"))
        return out

    def _tables(self) -> dict[int, tuple[int, str]]:
        """Code addresses in tables a dispatcher is given in HL (`ld hl,table / jp dispatch`, or `rst $20`): every
        word up to the first that isn't a plausible function in the bank the caller had mapped."""
        f, out = self.found, {}
        for from_flat, from_cpu, table, (s1, s2), callee in f.with_hl:
            if callee not in f.dispatchers or table < 0x0100:
                continue
            tflat = resolve(table, from_flat, from_cpu, s1, s2, self.size)
            if tflat is None:
                continue
            for k in range(128):
                at = tflat + 2 * k
                if at + 1 >= self.size or (k and at % BANK == 0):
                    break
                word = self.data[at] | self.data[at + 1] << 8
                if word == 0 and k == 0:
                    continue  # a table's first entry is often 0: no handler for state 0
                cflat = resolve(word, from_flat, from_cpu, s1, s2, self.size)
                if cflat is None or not plausible(self.data, cflat, word):
                    break
                out.setdefault(cflat, (word, "table"))
        return out

    def default_base(self, bank: int) -> int | None:
        """Where a bank no code was followed into most likely runs: a game that only ever picks slot 2's bank keeps
        bank 1 in slot 1, so its other banks run from slot 2 (0x8000). None: no telling (the power-on mapping)."""
        w = self.found.slot_writes
        if bank >= 2 and self.mapper and w.get(2) and not w.get(1):
            return 0x8000
        return None

    def _bank_bases(self) -> None:
        """The CPU address each bank's code was found running at: the slot most of its functions run from."""
        votes: dict[int, dict[int, int]] = {}
        for flat, (cpu, _why) in self.found.starts.items():
            if cpu >= 0x4000:
                v = votes.setdefault(flat // BANK, {})
                v[cpu & ~(BANK - 1)] = v.get(cpu & ~(BANK - 1), 0) + 1
        self.found.bank_base = {b: max(v, key=v.get) for b, v in votes.items()}


_SYM = re.compile(r"^\s*([0-9A-Fa-f]{1,4}):([0-9A-Fa-f]{4})\s+([A-Za-z_.@$][\w.@$]*)\s*$")


def read_sym(text: str) -> dict[tuple[int, int], str]:
    """A WLA-DX symbol file's labels: {(bank, CPU address): name}, from its [labels] section (or a file of bare
    `bank:address name` lines). Local labels (starting with `_` or `@`, or holding a dot) are left out."""
    out: dict[tuple[int, int], str] = {}
    section = "labels"
    for line in text.splitlines():
        line = line.split(";", 1)[0].strip()
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1].strip().lower()
            continue
        if section != "labels" or not (m := _SYM.match(line)):
            continue
        name = m.group(3)
        if name.startswith(("_", "@")) or "." in name or "$" in name:
            continue
        out[(int(m.group(1), 16), int(m.group(2), 16))] = name
    return out


def sym_seeds(labels: dict[tuple[int, int], str], data: bytes) -> dict[int, tuple[int, str]]:
    """Seeds from a symbol file's labels that point at code in the ROM: {flat: (cpu, "sym")}."""
    out = {}
    for (bank, cpu), _name in labels.items():
        if cpu >= 0xC000:
            continue
        flat = cpu if cpu < 0x4000 else bank * BANK + (cpu & (BANK - 1))
        if flat < len(data) and plausible(data, flat, cpu):
            out[flat] = (cpu, "sym")
    return out
