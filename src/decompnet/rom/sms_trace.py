"""SMS/GG static discovery with full mapper/bus snapshots.

Follow reset, calls, jumps and bounded dispatch tables using the shared address model. Known mapper stores
update bank and RAM selection together; the next instruction is fetched from the resulting source. A call
carries all mapping fields, and joined entries retain only facts their callers share. Sparse WRAM contents
remain separate from device registers. Isolated symbols and sweep seeds establish only their own ROM window;
the reset recipe applies only to the reset root.

Function extents and dispatch tables remain heuristic. Path visitation retains distinct facts under explicit
per-function budgets. A separate bounded evaluator propagates ordinary callee effects.
Physical stack byte/flag emulation and interrupt restoration remain unqualified.
These limits are separate from preserving full bus state on the paths this tracer follows.
"""

from __future__ import annotations

import bisect

from . import sms_calls, sms_effects, sms_registers, sms_seeds, sms_stack, sms_trace_writes, z80
from .sms_mapping import BusState, Mapper, REGISTERS, join
from .sms_mapping import entry_state as entry_state  # legacy Sega helper; analysis uses the selected model
from .sms_mapping import bank_mask as bank_mask  # preserve the previous helper import
from .sms_decode import decode as _decode, can_start as can_start, plausible as plausible
from .sms_paths import Limits, Paths
from .sms_analysis import Budget, CONVERGENCE_ROUNDS
from .sms_registers import _WRITES_HL as _WRITES_HL
from .sms_registers import _WRITES_DE as _WRITES_DE
from .sms_registers import _WRITES_BC as _WRITES_BC
from .sms_state import ARG, Found, State

BANK = 0x4000
VECTORS = (0x0000, 0x0008, 0x0010, 0x0018, 0x0020, 0x0028, 0x0030, 0x0038, 0x0066)
MAPPER = REGISTERS  # preserve the previous Sega-specific import


def resolve(target: int, here_flat: int, here_cpu: int, s1, s2, size: int, s0=0, *,
            mapping: BusState | None = None, mapper: str = "sega") -> int | None:
    """Compatibility adapter for trace bank tuples; explicit bus state takes precedence.

    The tuple adapter describes cartridge-only execution with RAM selection off. Full bus contexts
    must be passed as `mapping`; in that case the source instruction never overrides updated banks.
    """
    if mapping is None:
        banks = [s0, s1, s2]
        if (0 if mapper == "codemasters" else 0x0400) <= here_cpu < 0xC000 and \
                0 <= here_flat < size and here_flat % BANK == here_cpu % BANK:
            banks[here_cpu // BANK] = here_flat // BANK
        mapping = BusState.cartridge_only([v if type(v) is int else None for v in banks])
    return Mapper(mapper, size).resolve(target, mapping).rom_offset


def inferred_inline(found: Found) -> dict[int, int]:
    """{routine: bytes} for routines every evaluated unconditional call came back the same nonzero number of bytes
    past: operands they read after their call. A declared `operands` correction takes precedence over this."""
    return {flat: next(iter(past)) for flat, past in sorted(found.returned_past.items())
            if len(past) == 1 and 0 not in past}


class Tracer:
    def __init__(self, data: bytes, paged: set[int] | None = None, hints: dict | None = None, *,
                 mapper: str = "sega", reset: BusState | None = None, limits: Limits | None = None,
                 call_limits: Limits | None = None, call_depth: int = 8, budget: Budget | None = None):
        """Trace under an explicit mapper/reset recipe; isolated seeds establish only their own ROM window.
        `paged` remains accepted for callers of the previous tracer; absence of writes never establishes banks.
        `hints`: data spans, inline operands and nonreturning routines (see sms.functions).
        """
        self.data, self.size = data, len(data)
        self.hints = hints or {}
        cov = self.hints.get("coverage")  # (what an emulator only saw read is data too)
        self.data_spans: list[tuple[int, int]] = []  # merged, in order
        for a, n in sorted(list(self.hints.get("data") or []) + (cov.runs("read") if cov is not None else [])):
            if self.data_spans and a <= sum(self.data_spans[-1]):
                last = self.data_spans[-1]
                self.data_spans[-1] = (last[0], max(sum(last), a + n) - last[0])
            else:
                self.data_spans.append((a, n))
        self.model = Mapper(mapper, self.size)
        self.reset = reset if reset is not None else self.model.reset()
        self.mapper = mapper != "mapperless"
        self.game_gear = self.hints.get("platform") == "gg"  # (its own mode: ports $00-$06 are the console's)
        self.limits = limits or Limits()
        self.budget = budget or Budget()
        self.calls = sms_calls.Evaluator(data, self.model, hints=self.hints, in_data=self.in_data,
                                        limits=call_limits, depth=call_depth, budget=self.budget)
        self.found = Found()
        self.known: set[int] = set()  # function starts as the last round left them (and the seeds)

    def follow(self, seeds: dict[int, tuple[int, str]], rounds: int = CONVERGENCE_ROUNDS) -> Found:
        """The functions reachable from `seeds` (flat -> (cpu, why)), in rounds until nothing changes: each round
        starts again from the seeds with what the last one learned (far jumps and tables that start functions,
        functions that don't return, bank switchers). The reset vector starts with the power-on banks; any other
        seed with what its callers had mapped, as far as they agree (else `unknown`)."""
        if type(rounds) is not int or not 1 <= rounds <= 64:
            raise ValueError("convergence rounds must be between 1 and 64")
        more: dict[int, tuple[int, str]] = {}  # far jumps and tables, as the last round found them
        before = None
        for _ in range(rounds):
            if not self.budget.round():
                break
            todo = self.budget.seeds({**more, **seeds})
            self.known = set(todo)
            self._round(todo)
            self._returning()
            more = {**self._far_jumps(), **self._tables()}
            now = (frozenset(self.found.starts.items()), frozenset(self.found.switchers.items()),
                   frozenset(self.found.returns), frozenset(self.found.takes_return), frozenset(more),
                   frozenset((flat, frozenset(past)) for flat, past in self.found.returned_past.items()),
                   frozenset((flat, frozenset(states)) for flat, states in self.found.entered.items()))
            if now == before:
                break
            before = now
        else:
            self.budget.note("convergence round budget exhausted")
        self.budget.qualify(self.found, self.model)
        self._bank_bases()
        return self.found

    # -- one round

    def _round(self, seeds: dict[int, tuple[int, str]]) -> None:
        f = self.found
        prev, f.entered, f.starts, f.with_hl, f.jumps, f.anchors = f.entered, {}, {}, [], [], set()
        f.indexed, f.tails, f.code, f.returned_past = [], {}, {}, {}
        queue = [(flat, cpu, why, self.reset if (flat, cpu, why) == (0, 0, "vector") else None)
                 for flat, (cpu, why) in sorted(seeds.items(), reverse=True)]  # reset before isolated entries
        for flat, _cpu, _why, m in queue:
            if m is not None:
                f.entered.setdefault(flat, set()).add(m)
        seen: set[int] = set()
        while queue:
            if self.budget.stopped:
                break
            flat, cpu, why, mapping = queue.pop()
            if why != "jump" and can_start(self.data, flat, cpu):
                f.anchors.add(flat)
            if flat in seen or not can_start(self.data, flat, cpu) or self.in_data(flat):
                continue
            if not self.budget.enter(flat, cpu):
                break
            seen.add(flat)
            f.starts.setdefault(flat, (cpu, why))
            # a slot's bank holds inside a function only when everything that enters it agrees on it
            entries = prev.get(flat, set()) | ({mapping} if mapping is not None else set())
            context = join(entries) if entries else self.model.entry(flat, cpu)
            for cflat, ccpu, m, how in self._trace(flat, cpu, State(context, ARG)):
                f.entered.setdefault(cflat, set()).add(m)
                queue.append((cflat, ccpu, how, m))

    def _returning(self) -> None:
        """A function returns when a path of it does: a return, or a tail jump to a function that returns or to where
        no one can tell (another bank nobody knows, an address worked out at run time: what it reaches returns)."""
        f = self.found
        changed = True
        while changed:
            changed = False
            for entry, outs in f.tails.items():
                if entry not in f.returns and (None in outs or outs & f.returns):
                    f.returns.add(entry)
                    changed = True

    def _no_return(self, flat: int) -> bool:
        """An explicit correction, never the absence of a traced return."""
        return flat in self.hints.get("noreturn", ())

    def in_data(self, flat: int) -> bool:
        """In bytes a correction (or coverage) says aren't code."""
        k = bisect.bisect_right(self.data_spans, (flat, 1 << 30)) - 1
        return k >= 0 and self.data_spans[k][0] <= flat < sum(self.data_spans[k])

    def _trace(self, entry: int, entry_cpu: int, st: State) -> list[tuple[int, int, BusState, str]]:
        """Follow one function; returns the functions it calls or jumps to: (flat, cpu, the banks mapped then,
        "call" | "jump")."""
        f, data, size = self.found, self.data, self.size
        out: list[tuple[int, int, BusState, str]] = []
        tails = f.tails.setdefault(entry, set())
        work = [(entry, entry_cpu, st)]
        paths = Paths(self.limits)
        tables_at, indexed_at = len(f.with_hl), len(f.indexed)
        while work and not self.budget.stopped:
            flat, cpu, st = work.pop()
            while 0 <= flat < size and not self.in_data(flat):
                if self.model.resolve(cpu, st.mapping).rom_offset != flat:
                    break
                if not paths.admit(flat, cpu, st):
                    break
                if not self.budget.step():
                    break
                text, ln = _decode(data, flat, cpu)
                if text.startswith("db "):
                    break
                f.code[flat] = ln
                st.n += 1
                skip = 0  # bytes after a call that the routine called reads (a correction says how many)
                kind, target = z80.flow(text)
                if reason := sms_effects.interrupt_limit(text):
                    self._unresolved(entry, reason)
                    if text == "halt":
                        break  # wake-up requires an interrupt/context this tracer has not qualified
                if reason := sms_stack.instruction(st, text, kind, self.model):
                    self._unresolved(entry, reason)
                    break
                # Device writes select banks and also write WRAM. WRAM aliases never select a bank.
                writes = sms_effects.memory_writes(text, {"a": st.a, "hl": st.hl, "de": st.de, "bc": st.bc})
                source_change = sms_effects.port_may_change_source(text, st.bc, game_gear=self.game_gear)
                if reason := sms_stack.write_alias(st, writes):
                    self._unresolved(entry, reason)
                    break
                write_limits = sms_trace_writes.limits(writes, self.model)
                for reason in write_limits:
                    self._unresolved(entry, reason)
                if source_change or any(write.cpu is None for write in writes) or write_limits:
                    self._unresolved(entry, "explicit memory or source-control write is unqualified")
                    f.unknown_writes.add(entry)
                    f.switchers.pop(entry, None)
                for slot_reg, val in ((write.cpu, write.value) for write in writes):
                    if (slot := self.model.register_slot(slot_reg)) is not None:
                        if not (slot == 1 and val == 1) and not (slot == 0 and val == 0):
                            f.slot_writes[slot] = f.slot_writes.get(slot, 0) + 1
                        if val == ARG and entry not in f.unknown_writes:
                            f.switchers.setdefault(entry, slot)
                sms_trace_writes.apply(st, writes, source_change, self.model)
                if text.startswith("push "):
                    st.pushed = True
                    reg = text[5:]
                    st.stack.append(sms_stack.StackWord(reg, st.a if reg == "af" else st.hl if reg == "hl" else st.de
                                                       if reg == "de" else st.bc if reg == "bc" else None))
                if (text == "pop hl" or text.startswith("ex (sp), ")) and not st.pushed and st.n <= 3:
                    f.takes_return.add(entry)  # its return address, first thing: the table that follows its call
                computed = None  # a computed call: the address pushed to come back to (`push de / jp (hl)`)
                if text in ("jp (hl)", "jp (ix)", "jp (iy)"):
                    if st.stack:
                        if (computed := sms_stack.address(st)) is not None:
                            sms_stack.take(st)
                        else:
                            self._unresolved(entry, "pushed value does not establish a complete return address")
                    to = st.hl if text == "jp (hl)" else None
                    tflat = self.model.resolve(to, st.mapping).rom_offset if to is not None else None
                    if to is None:
                        f.dispatchers.add(entry)  # to an address it worked out: a dispatcher
                        base = st.fresh(st.base)
                        if base is not None and computed is None:  # a table it indexed itself
                            f.indexed.append((flat, cpu, base, st.mapping, st.fresh(st.index) or st.fresh(st.bound)))
                    elif tflat is not None and tflat != entry:
                        out.append((tflat, to, st.mapping, "call" if computed is not None else "jump"))
                    if computed is None:
                        tails.add(tflat if to is not None else None)
                elif text == "ret" and st.stack and st.pushed:
                    if (to := sms_stack.address(st)) is None:
                        self._unresolved(entry, "pushed value does not establish a complete return address")
                        break
                    sms_stack.take(st)  # `push rr / ret`: a jump to what it pushed, not a return
                    tflat = self.model.resolve(to, st.mapping).rom_offset
                    if tflat is not None and tflat != entry:
                        out.append((tflat, to, st.mapping, "jump"))
                        f.jumps.append((entry, tflat, to, st.mapping))
                    tails.add(tflat)
                    break
                elif kind in ("ret", "cret"):
                    f.returns.add(entry)
                if target is not None and kind in ("call", "jump", "cjump"):
                    tflat = self.model.resolve(target, st.mapping).rom_offset
                    if tflat is not None:
                        inside = (tflat == entry and target == entry_cpu) or (
                            tflat // BANK == entry // BANK and target >> 14 == cpu >> 14 and tflat != entry
                            and tflat not in self.known)
                        if kind != "call" and tflat != entry:  # every jump: the next round sees which are far
                            f.jumps.append((entry, tflat, target, st.mapping))
                        if kind == "call" or not inside:
                            if tflat != entry:  # a call, or a jump to another function: a tail call
                                out.append((tflat, target, st.mapping, "call" if kind == "call" else "jump"))
                                if st.hl is not None:
                                    f.with_hl.append((flat, cpu, st.hl, st.mapping, tflat, st.fresh(st.bound)))
                                if kind == "jump":
                                    tails.add(tflat)
                        else:  # a branch within the function
                            work.append((tflat, target, self._branch(st, text)))
                    elif kind == "jump":
                        tails.add(None)  # into a bank no one knows, or RAM
                    if kind == "call":
                        conditional = "," in text
                        skip = (self.hints.get("inline") or {}).get(tflat, 0) if not conditional else 0
                        st, past = self._call(entry, target, tflat, st, (cpu + ln) & 65535, out,
                                              skip=skip, conditional=conditional)
                        if st is None:
                            break
                        skip += past  # operands the callee was found to read and return past
                if kind != "call":
                    self._registers(st, text)
                if computed is not None:  # back from the computed call: on at the address it pushed
                    st, _ = self._call(entry, to, tflat, st, computed, out, already_pushed=True)
                    if st is None:
                        break
                    back = self.model.resolve(computed, st.mapping).rom_offset
                    if back is not None and back // BANK == entry // BANK:
                        nxt = st.copy()
                        nxt.a, nxt.hl, nxt.de, nxt.bc = None, None, None, None
                        work.append((back, computed, nxt))
                    break
                if kind in ("ret", "jump"):
                    break
                if kind in ("cjump", "cret"):  # what the condition says on the way on (`cp 5 / jr nc`: A < 5)
                    self._condition(st, text, taken=False)
                nxt = flat + max(1, ln) + skip
                next_cpu = cpu + max(1, ln) + skip
                mapped = self.model.resolve(next_cpu, st.mapping).rom_offset
                if mapped is None:
                    break
                if mapped != nxt:
                    out.append((mapped, next_cpu, st.mapping, "jump"))
                    tails.add(mapped)
                    break
                if nxt // BANK != flat // BANK:
                    break  # ran off the end of the bank
                flat, cpu = mapped, next_cpu
        if paths.exhausted:
            f.exhausted.setdefault(entry, set()).update(paths.exhausted)
        if entry in f.exhausted:
            # Missing paths cannot supply complete mapper/helper or dispatch summaries. Keep known target
            # coordinates as conditional entries, without carrying singleton caller facts into their bodies.
            f.switchers.pop(entry, None)
            del f.with_hl[tables_at:]
            del f.indexed[indexed_at:]
            out = [(at, pc, self.model.entry(at, pc), how) for at, pc, _mapping, how in out]
        return list(dict.fromkeys(out))

    def _unresolved(self, entry, reason):
        self.found.unresolved.setdefault(entry, set()).add(reason)
        if "budget exhausted" in reason:
            self.found.exhausted.setdefault(entry, set()).add(reason)

    def _call(self, entry, target, flat, state, return_cpu, entries, *, skip=0, conditional=False, already_pushed=False):
        """(The caller's state after the call or None when it never returns, and how many bytes past the call it
        comes back when the callee was found to read undeclared operands there.)"""
        result = sms_calls.Result() if self._no_return(flat) else \
            self.calls.evaluate(target, state, return_cpu, skip=skip, already_pushed=already_pushed)
        if result.inline and conditional:
            result.reasons.add("conditional inline continuation is unqualified")
        if flat is not None and not result.reasons and not skip and not already_pushed and not conditional \
                and (result.returns or result.inline):
            self.found.returned_past.setdefault(flat, set()).add(result.inline)
        for reason in result.reasons:
            self._unresolved(entry, reason)
        nested = result.entries[1:] if result.entries and result.entries[0][:2] == (flat, target) else result.entries
        entries.extend((at, pc, self.model.entry(at, pc) if result.reasons else mapping, "call")
                       for at, pc, mapping in nested)
        return result.resume(state, conditional=conditional), 0 if result.reasons else result.inline

    def _branch(self, st: State, text: str) -> State:
        out = st.copy()
        self._condition(out, text, taken=True)
        return out

    @staticmethod
    def _condition(st: State, text: str, taken: bool) -> None:
        """After `cp n`, the carry says A < n: the path where it's set has A bounded to n values (an index); the
        other has A at least n."""
        cond = text.split(None, 1)[1].split(",")[0].strip() if " " in text else ""
        n = st.fresh(st.cmp)
        if n is None or cond not in ("c", "nc"):
            return
        if (cond == "c") == taken:
            st.bound = (st.n, n, True)
        else:
            st.low = (st.n, n)

    def _registers(self, st: State, text: str) -> None:
        sms_registers.apply(st, text, self.model)

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
        """Code addresses in tables: the ones a dispatcher is given in HL (`ld hl,table / jp dispatch`, or `rst
        $20`), and the ones a function indexes itself before `jp (hl)`."""
        f, out = self.found, {}
        for from_flat, from_cpu, table, slots, callee, bound in f.with_hl:
            if callee in f.dispatchers and table >= 0x0100:
                out.update({k: v for k, v in self._table(from_flat, from_cpu, table, slots, bound).items() if k not in out})
        for from_flat, from_cpu, table, slots, bound in f.indexed:
            out.update({k: v for k, v in self._table(from_flat, from_cpu, table, slots, bound).items() if k not in out})
        return out

    def _table(self, from_flat: int, from_cpu: int, table: int, slots: BusState, bound: tuple | None) -> dict:
        """The functions a table holds, in the bank its reader had mapped: words, or `jp` instructions (a table of
        jumps, three bytes each). With the index bounded exactly (`cp 5 / jr nc`), that many entries (one that
        isn't code is a gap: no handler there); else up to the first that doesn't read like a function's start, and
        no more than a mask allows (`and $7f`)."""
        tflat = self.model.resolve(table, slots).rom_offset
        out: dict[int, tuple[int, str]] = {}
        if tflat is None:
            return out
        limit, exact = bound if bound else (None, False)
        count = limit if limit and limit <= 128 else 128
        capped = bool(limit) and not exact  # (a mask's ceiling: one that isn't code is skipped, not the end)
        bound = limit if exact and limit <= 128 else None
        if self.data[tflat] == 0xC3:  # jp nnnn, jp nnnn, ...: each entry is code, the jump is its own
            for k in range(count):
                at = tflat + 3 * k
                if at + 2 >= self.size or self.data[at] != 0xC3 or (k and at // BANK != tflat // BANK):
                    break
                out[at] = (table + 3 * k, "table")
            return out
        lowest = None  # the lowest handler past the table: between the table and it are only the table's words
        for k in range(count):
            at = tflat + 2 * k
            if at + 1 >= self.size or (k and at // BANK != tflat // BANK):
                break
            word = self.data[at] | self.data[at + 1] << 8
            if word == 0:
                if k == 0 or bound:
                    continue  # a table's first entry is often 0: no handler for state 0
                break
            if not bound and len(out) >= 4 and lowest is not None and table < word < lowest:
                break  # into the table's own bytes, or what follows them: past the table's end
            cflat = self.model.resolve(word, slots).rom_offset
            if cflat is None:
                if bound:
                    continue
                break
            if not plausible(self.data, cflat, word):
                if bound or capped:
                    continue
                break
            if word > table:
                lowest = word if lowest is None else min(lowest, word)
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
            if cpu >= 0x0400 or self.model.kind == "codemasters":
                v = votes.setdefault(flat // BANK, {})
                v[cpu & ~(BANK - 1)] = v.get(cpu & ~(BANK - 1), 0) + 1
        self.found.bank_base = {b: max(v, key=v.get) for b, v in votes.items()}


def read_sym(text: str, seeds: bool = False, *, layout=None, image=None, mapper='sega', physical=False) -> dict[tuple[int, int], str]:
    """Normalize declared WLA geometry; legacy physical code records require explicit physical=True."""
    from .wla_symbols import read_names

    return read_names(text, seeds, layout=layout, image=image, mapper=mapper, physical=physical)


def sym_seeds(labels: dict[tuple[int, int], str], data: bytes, *, mapper: str = "sega") -> dict[int, tuple[int, str]]:
    """Seeds from a symbol file's labels that point at code in the ROM: {flat: (cpu, "sym")}."""
    out = {}
    for flat, cpu in sms_seeds.symbol_targets(labels, Mapper(mapper, len(data))):
        if plausible(data, flat, cpu):
            out[flat] = (cpu, "sym")
    return out
