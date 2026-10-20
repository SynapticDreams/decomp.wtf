"""SMS/GG cartridge address resolution from explicit bus facts.

CPU addresses, physical cartridge offsets and assembler section geometry are distinct.
Reset state is an explicit choice: the fully unknown state never invents cartridge banks.
References: SMS Power's MemoryMap and Mappers development pages. Hardware-specific or
undeclared wiring remains unresolved; this module does not emulate RAM contents or a BIOS.
The Korean board (MAME sega8_korean_device, Gearsystem KoreanMemoryRule) fixes slots 0 and 1 to banks 0 and 1 and
selects slot 2 by a write to exactly $A000; both emulators reset slot 2 to bank 2 and have no Sega registers.
"""
from __future__ import annotations

from dataclasses import dataclass, replace

if __package__:
    from . import sms_codemasters as cm
else:  # the same resolver is copied into standalone exports
    import sms_codemasters as cm

BANK = 0x4000
REGISTERS = {0xFFFD: 0, 0xFFFE: 1, 0xFFFF: 2}
KOREAN = {0xA000: 2}  # the Korean board's only selector (write-only: reads there are ROM)


def bank_mask(size: int) -> int:
    banks = max(1, (size + BANK - 1) // BANK)
    return (1 << (banks - 1).bit_length()) - 1


def wram_address(cpu: int) -> int | None:
    """Canonical alias if the selected source is work RAM; this does not establish that selection."""
    return 0xC000 + (cpu & 0x1FFF) if 0xC000 <= cpu <= 0xFFFF else None


@dataclass(frozen=True)
class Address:
    cpu: int
    space: str
    offset: int | None = None
    reason: str = ""
    bank: int | None = None

    @property
    def rom_offset(self) -> int | None:
        return self.offset if self.space == "rom" else None


@dataclass(frozen=True)
class BusState:
    # Effective ROM banks and raw register selections differ when bank shifting is active.
    banks: tuple[int | None, ...] = (None, None, None)
    registers: tuple[int | None, ...] = (None, None, None)
    control: int | None = None  # values only for control_known bits; use control_bits(255) for a complete byte
    cartridge: bool | None = None
    bios: bool | None = None
    wram: bool | None = None
    other_source: bool | None = None
    rom_modified: bool = False
    control_known: int | None = None  # known bits of control; unknown bit values are not raw register facts

    def __post_init__(self):
        for values in (self.banks, self.registers):
            if not isinstance(values, tuple) or len(values) != 3 or any(v is not None and (type(v) is not int or not 0 <= v <= 255) for v in values):
                raise ValueError("a mapping state has three byte-sized bank selections or unknown values")
        if self.control is not None and (type(self.control) is not int or not 0 <= self.control <= 255):
            raise ValueError("mapper control is a byte or unknown")
        if self.control_known is not None and (type(self.control_known) is not int or not 0 <= self.control_known <= 255):
            raise ValueError("known control bits form a byte-sized mask")
        known = (255 if self.control is not None else 0) if self.control_known is None else self.control_known
        known = known if self.control is not None else 0
        object.__setattr__(self, "control_known", known)
        object.__setattr__(self, "control", self.control & known if known else None)
        if any(v is not None and type(v) is not bool for v in (self.cartridge, self.bios, self.wram, self.other_source)):
            raise ValueError("bus selections are true, false or unknown")
        if type(self.rom_modified) is not bool:
            raise ValueError("modified cartridge state is a boolean")

    @classmethod
    def cartridge_only(cls, banks=(None, None, None), *, control=0, registers=(None, None, None), control_known=None):
        """An explicitly cartridge-only analysis context, not an assertion about every console boot."""
        return cls(banks=tuple(banks), registers=tuple(registers), control=control, cartridge=True,
                   bios=False, wram=True, other_source=False, control_known=control_known)

    def control_bits(self, mask: int) -> int | None:
        """Return requested bits only when every one is established."""
        return (self.control or 0) & mask if self.control_known & mask == mask else None

    def control_flag(self, mask: int) -> bool | None:
        value = self.control_bits(mask)
        return bool(value) if value is not None else None


@dataclass(frozen=True)
class Mapper:
    kind: str
    size: int

    def __post_init__(self):
        if self.kind not in ("sega", "mapperless", "codemasters", "korean"):
            raise ValueError("this mapping model supports Sega, mapperless, qualified Codemasters and Korean cartridges")
        if type(self.size) is not int or not 0x2000 <= self.size <= 0x400000 or self.size % 0x2000:
            raise ValueError("invalid SMS/GG cartridge size")
        if self.kind == "mapperless" and self.size > 3 * BANK:
            raise ValueError("a mapperless cartridge cannot expose more than 48 KiB")
        if self.kind == "codemasters" and (not 0x8000 <= self.size <= 0x80000 or self.size & (self.size - 1)):
            raise ValueError("qualified Codemasters images need a power-of-two size from 32 to 512 KiB")
        if self.kind == "korean" and (not 0x8000 <= self.size or self.size & (self.size - 1)):
            raise ValueError("qualified Korean images need a power-of-two size of at least 32 KiB")

    def reset(self) -> BusState:
        """Selected wiring/recipe, without assigning one mapper's raw registers to another."""
        if self.kind == "mapperless":
            return BusState.cartridge_only((0, 1, 2), control=None)
        if self.kind == "codemasters":
            return BusState.cartridge_only((0, 1, 0), registers=(0, 1, 0), control=0, control_known=cm.RAM)
        if self.kind == "korean":  # (both emulators' recipe; the selector latch itself is never read back)
            return BusState.cartridge_only((0, 1, 2 & bank_mask(self.size)), control=None)
        # Sega's selected 315-5235/emulator recipe is not a reset guarantee for every chip revision.
        banks = tuple(bank & bank_mask(self.size) for bank in (0, 1, 2))
        return BusState.cartridge_only(banks, registers=(0, 1, 2))

    def entry(self, flat: int, cpu: int) -> BusState:
        """Conditional ROM-entry facts under this model, separate from reset and section placement."""
        if self.kind == "mapperless":
            return BusState.cartridge_only((0, 1, 2), control=None)
        if self.kind == "codemasters":
            banks = [None, None, None]
            if 0 <= flat < self.size and 0 <= cpu < 0xC000 and flat % BANK == cpu % BANK:
                banks[cpu // BANK] = flat // BANK
            known = cm.RAM if banks[2] is not None and cpu >= 0xA000 else 0
            return BusState.cartridge_only(banks, control=0 if known else None, control_known=known)
        if self.kind == "korean":  # slots 0 and 1 are wired; only slot 2 can be established by entry geometry
            fixed = 0 <= flat < self.size and 0x8000 <= cpu < 0xC000 and flat % BANK == cpu % BANK
            return BusState.cartridge_only((0, 1, flat // BANK if fixed else None), control=None)
        return entry_state(flat, cpu, self.size)

    def register_slot(self, cpu: int) -> int | None:
        """The canonical bank selector at a CPU address, if this model has one there."""
        registers = cm.SELECTORS if self.kind == "codemasters" else REGISTERS if self.kind == "sega" else \
            KOREAN if self.kind == "korean" else {}
        return registers.get(cpu) if type(cpu) is int else None

    def is_mapper_register(self, cpu: int) -> bool:
        return type(cpu) is int and ((self.kind == "sega" and cpu == 0xFFFC) or self.register_slot(cpu) is not None)

    def resolve(self, cpu: int, state: BusState) -> Address:
        if type(cpu) is not int or not 0 <= cpu <= 0xFFFF:
            return Address(-1, "unknown", reason="outside the 16-bit CPU address space")
        if cpu >= 0xC000:
            if state.other_source is not False:
                return Address(cpu, "unknown", reason="other device/RAM selection is unresolved")
            high_ram = False if self.kind != "sega" or state.cartridge is False else \
                state.control_flag(0x10) if state.cartridge is True else None
            if high_ram is True:
                if state.wram is not False:
                    return Address(cpu, "unknown", reason="cartridge RAM may contend with system RAM")
                return Address(cpu, "cart_ram", reason="upper cartridge RAM wiring is not declared")
            if high_ram is None or state.wram is None:
                return Address(cpu, "unknown", reason="upper RAM source is unresolved")
            return Address(cpu, "wram", cpu & 0x1FFF) if state.wram else Address(cpu, "unmapped", reason="RAM disabled")
        if state.other_source is not False or state.bios is None or state.cartridge is None:
            return Address(cpu, "unknown", reason="cartridge/BIOS/device selection is unresolved")
        if state.bios:
            if state.cartridge:
                return Address(cpu, "unknown", reason="BIOS and cartridge may both drive the bus")
            return Address(cpu, "bios", reason="BIOS selected; its layout is not declared")
        if not state.cartridge:
            return Address(cpu, "unmapped", reason="cartridge disabled")
        if state.rom_modified:
            return Address(cpu, "unknown", reason="cartridge contents may have been modified")
        if self.kind == "mapperless" or (self.kind == "korean" and cpu < 0x8000):
            flat, bank = cpu, cpu // BANK
        elif self.kind == "sega" and cpu < 0x0400:
            flat, bank = cpu, 0
        else:
            if self.kind != "korean" and cpu >= (0xA000 if self.kind == "codemasters" else 0x8000):
                ram = state.control_flag(cm.RAM if self.kind == "codemasters" else 8)
                if ram is None:
                    return Address(cpu, "unknown", reason="slot 2 RAM selection is unresolved")
                if ram:
                    selected = state.control_bits(4) if self.kind == "sega" else None
                    return Address(cpu, "cart_ram", reason="cartridge RAM size/wiring is not declared",
                                   bank=selected >> 2 if selected is not None else None)
            bank = state.banks[cpu // BANK]
            if bank is None:
                return Address(cpu, "unknown", reason="ROM bank is unresolved")
            flat = bank * BANK + (cpu & (BANK - 1))
        if flat >= self.size:
            return Address(cpu, "unknown", reason="address exceeds supplied ROM; mirror wiring is not declared")
        return Address(cpu, "rom", flat, bank=bank)

    def write(self, state: BusState, cpu: int, value: int | None) -> BusState:
        if type(cpu) is not int or not 0 <= cpu <= 0xFFFF:
            raise ValueError("a mapper write requires a 16-bit CPU address")
        if value is not None and (type(value) is not int or not 0 <= value <= 255):
            raise ValueError("a mapper write is a byte or an unknown value")
        if self.kind == "mapperless":
            return state
        if self.kind == "codemasters":
            return cm.write(state, cpu, value, bank_mask(self.size))
        if self.kind == "korean":
            if cpu not in KOREAN:
                return state  # (ROM ignores the write; RAM keeps it, as the caller's RAM facts record)
            qualified = state.cartridge is True and value is not None
            return replace(state, banks=(*state.banks[:2], value & bank_mask(self.size) if qualified else None),
                           registers=(None, None, value if qualified else None))
        if cpu == 0xFFFC or cpu in REGISTERS:
            if state.cartridge is not True:
                return replace(state, banks=(None, None, None), registers=(None, None, None), control=None)
            if cpu == 0xFFFC:
                return replace(state, control=value, control_known=None)  # shifting waits for a bank-register write
            registers = list(state.registers)
            registers[REGISTERS[cpu]] = value
            shift_bits = state.control_bits(3)
            shift = None if shift_bits is None else (0, 0x18, 0x10, 8)[shift_bits]
            if shift and self.size != 0x80000:
                shift = None  # documented only for the 512 KiB mapper variant
            banks = tuple((v + shift) & bank_mask(self.size) if v is not None and shift is not None else None for v in registers)
            return replace(state, banks=banks, registers=tuple(registers))
        if 0 <= cpu < 0xC000 and state.cartridge is not False and state.control_flag(0x80) is not False:
            return replace(state, rom_modified=True)
        return state

    def unknown_write(self, state: BusState) -> BusState:
        """An unqualified byte store may select any register or change writable cartridge contents."""
        if self.kind == "mapperless":
            return state
        if self.kind == "codemasters":
            return replace(state, banks=(None, None, None), registers=(None, None, None), control=None)
        if self.kind == "korean":
            return replace(state, banks=(*state.banks[:2], None), registers=(None, None, None))
        return replace(state, banks=(None, None, None), registers=(None, None, None), control=None,
                       rom_modified=state.rom_modified or (
                           state.cartridge is not False and state.control_flag(0x80) is not False))


def entry_state(flat: int, cpu: int, size: int) -> BusState:
    """Conditional ROM entry evidence establishes its own window, never the other pageable windows."""
    banks: list[int | None] = [None, None, None]
    if 0 <= flat < size and 0 <= cpu < 0xC000 and flat % BANK == cpu % BANK and cpu >= 0x0400:
        banks[cpu // BANK] = flat // BANK
    # ROM in slot 2 establishes only that RAM is not selected there. It does not establish shift,
    # write-enable, upper RAM selection or raw bank latches. Entry geometry is not a reset recipe.
    known = 8 if banks[2] is not None else 0
    return BusState.cartridge_only(banks, control=0 if known else None, control_known=known)


def join(states) -> BusState:
    """Keep only facts shared by all incoming contexts; any possibly modified ROM stays unknown."""
    states = tuple(states)
    if not states:
        return BusState()

    def agreed(values):
        values = set(values)
        return next(iter(values)) if len(values) == 1 else None

    control, known = states[0].control or 0, 255
    for state in states:
        known &= state.control_known & ~(control ^ (state.control or 0)) & 255

    return BusState(
        banks=tuple(agreed(s.banks[k] for s in states) for k in range(3)),
        registers=tuple(agreed(s.registers[k] for s in states) for k in range(3)),
        control=control & known if known else None, control_known=known,
        cartridge=agreed(s.cartridge for s in states), bios=agreed(s.bios for s in states),
        wram=agreed(s.wram for s in states), other_source=agreed(s.other_source for s in states),
        rom_modified=any(s.rom_modified for s in states),
    )


def rom_coordinate(model: Mapper, bank: int, cpu: int, mapping: BusState | None = None) -> Address:
    """Validate an explicit physical ROM-bank/CPU coordinate; never reattribute contradictory coordinates."""
    flat = bank * BANK + (cpu & (BANK - 1))
    state = mapping if mapping is not None else model.entry(flat, cpu)
    result = model.resolve(cpu, state)
    if result.rom_offset is not None and result.offset != flat:
        return Address(cpu, "unknown", reason="coordinate bank contradicts the selected cartridge mapping")
    return result
