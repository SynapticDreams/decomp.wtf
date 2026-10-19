"""Bounded evaluation of ordinary callees using actual incoming register and bus facts.

Every return path contributes to the caller's continuation. Unknown sources, unsupported return
traffic and exhausted evaluation remain unresolved. The stack is virtual: physical SP/device aliases
and asynchronous interrupts need separate qualification. This is static interpretation, not a CPU core.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from . import sms_effects, sms_registers, sms_trace_writes, z80
from .sms_decode import decode
from .sms_mapping import BusState, Mapper, join
from .sms_paths import Limits, Paths
from .sms_state import State


@dataclass(frozen=True)
class StackWord:
    kind: str
    value: object


@dataclass
class Result:
    returns: list[State] = field(default_factory=list)
    reasons: set[str] = field(default_factory=set)
    entries: list[tuple[int, int, BusState]] = field(default_factory=list)

    def resume(self, caller: State, *, conditional: bool = False) -> State | None:
        if self.reasons:
            out = caller.copy()
            out.mapping, out.mem, out.stack = BusState(), {}, []
        else:
            states = self.returns + ([caller] if conditional else [])
            if not states:
                return None
            out = caller.copy()
            out.mapping = join(state.mapping for state in states)
            out.mem = {key: value for key, value in states[0].mem.items()
                       if all(state.mem.get(key) == value for state in states[1:])}
        out.a = out.hl = out.de = out.bc = None
        out.cmp = out.low = out.bound = out.index = out.base = None
        return out


class Evaluator:
    def __init__(self, data: bytes, model: Mapper, *, hints=None, in_data=lambda _flat: False,
                 limits: Limits | None = None, depth: int = 8):
        if type(depth) is not int or not 1 <= depth <= 64:
            raise ValueError("call depth must be between 1 and 64")
        self.data, self.model = data, model
        self.hints, self.in_data = hints or {}, in_data
        self.limits, self.depth = limits or Limits(steps=2048), depth

    def evaluate(self, target: int, caller: State, return_cpu: int, *, skip: int = 0) -> Result:
        return self._frame(target, caller, return_cpu, skip, 0, [self.limits.steps])

    def _frame(self, target, caller, return_cpu, skip, depth, fuel):
        result = Result()
        if (flat := self.model.resolve(target, caller.mapping).rom_offset) is not None and not self.in_data(flat):
            result.entries.append((flat, target, caller.mapping))
        if depth >= self.depth:
            result.reasons.add("call depth budget exhausted")
            return result
        st = State(caller.mapping, caller.a, caller.hl, caller.de, caller.bc,
                   dict(caller.mem), [StackWord("return", return_cpu)])
        work, paths = [(target, st)], Paths(self.limits)
        expected = (return_cpu + skip) & 65535
        while work:
            cpu, st = work.pop()
            while True:
                flat = self.model.resolve(cpu, st.mapping).rom_offset
                if flat is None or self.in_data(flat):
                    result.reasons.add("callee instruction source is unresolved or declared data")
                    break
                if not paths.admit(flat, cpu, st):
                    break
                if fuel[0] <= 0:
                    result.reasons.add("call instruction budget exhausted")
                    break
                fuel[0] -= 1
                text, length = decode(self.data, flat, cpu)
                if text.startswith("db "):
                    result.reasons.add("callee instruction is undecoded")
                    break
                if text in ("halt", "ei"):
                    result.reasons.add("callee interrupt-dependent continuation is unqualified")
                    break
                st.n += 1
                next_cpu = (cpu + length) & 65535
                kind, to = z80.flow(text)
                if text.startswith("jp ("):
                    kind, to = "jump", st.hl if text == "jp (hl)" else None
                if text in ("reti", "retn"):
                    result.reasons.add("interrupt return in an ordinary callee is unqualified")
                    break
                writes = sms_effects.memory_writes(text, {"a": st.a, "hl": st.hl, "de": st.de, "bc": st.bc})
                source_change = sms_effects.port_may_change_source(text, st.bc)
                if any(write.cpu is None for write in writes) or source_change:
                    result.reasons.add("callee has unqualified memory or source-control writes")
                    break
                if text.startswith("ld sp, ") or text in ("inc sp", "dec sp"):
                    result.reasons.add("callee changes physical stack placement")
                    break
                sms_trace_writes.apply(st, writes, source_change, self.model)
                if text.startswith("push "):
                    reg = text[5:]
                    st.stack.append(StackWord(reg, st.a if reg == "af" else getattr(st, reg, None)))
                    st.pushed = True
                elif text.startswith("pop "):
                    if not st.stack:
                        result.reasons.add("callee reads beyond its virtual return stack")
                        break
                    saved, reg = st.stack.pop(), text[4:]
                    value = saved.value
                    if reg == "af" and saved.kind != "af":
                        value = value >> 8 if type(value) is int else None
                    elif reg != "af" and saved.kind == "af":
                        value = None  # flags were not tracked as the low byte
                    if reg in ("af", "hl", "de", "bc"):
                        setattr(st, "a" if reg == "af" else reg, value)
                elif kind in ("ret", "cret"):
                    returned = st.copy()
                    if not returned.stack or returned.stack[-1].kind == "af":
                        result.reasons.add("callee return destination is unqualified")
                    else:
                        destination = returned.stack.pop().value
                        if destination == expected and not returned.stack:
                            result.returns.append(returned)
                        elif type(destination) is int and returned.stack:
                            work.append((destination, returned))  # a pushed computed continuation
                        else:
                            result.reasons.add("callee changes or loses the return continuation")
                    if kind == "ret":
                        break
                elif kind == "call" and to is not None:
                    callee = self.model.resolve(to, st.mapping).rom_offset
                    conditional = "," in text
                    inline = (self.hints.get("inline") or {}).get(callee, 0)
                    if inline and conditional:
                        result.reasons.add("conditional inline continuation is unqualified")
                        break
                    nested = Result(entries=[(callee, to, st.mapping)]) if callee is not None and \
                        callee in self.hints.get("noreturn", ()) else \
                        self._frame(to, st, next_cpu, inline, depth + 1, fuel)
                    result.reasons.update(nested.reasons)
                    result.entries.extend(nested.entries)
                    st = nested.resume(st, conditional=conditional)
                    if st is None or nested.reasons:
                        break
                    next_cpu = (next_cpu + inline) & 65535
                else:
                    sms_registers.apply(st, text, self.model)
                if kind in ("jump", "cjump"):
                    if to is None and text == "jp (hl)":
                        to = st.hl
                    if to is None:
                        result.reasons.add("callee jump destination is unresolved")
                    else:
                        work.append((to, st.copy()))
                    if kind == "jump":
                        break
                cpu = next_cpu
        result.reasons.update("call instruction budget exhausted" if reason == "instruction budget exhausted" else reason
                              for reason in paths.exhausted)
        return result
