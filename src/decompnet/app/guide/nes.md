# Matching NES code

The NES (Famicom) runs a **MOS 6502** (the Ricoh 2A03: a 6502 without decimal mode). The fork carries its own
disassembler for it (`decompnet.rom.mos6502`), checked against capstone's 6502 decoder on all 256 opcodes.

**Be realistic about matching.** Nearly every commercial NES game was written in assembly, so most of its
functions have no C source to find. What this lane does well: read a ROM, find its functions, search and name
them, and score an attempt exactly. Functions compiled with SDCC or GBDK-2020 (homebrew) can match byte for byte.

## What the importer does with a .nes file

- The file is read by its **iNES / NES 2.0 header** (`NES` and 0x1A). The 16-byte header, an optional 512-byte
  trainer, then the PRG ROM (the code and data) in 16 KiB units, then the CHR ROM (graphics). Only the PRG is code.
  Offsets in the app are **file offsets** (header included).
- The PRG is split into banks, shown at the CPU address the mapper usually puts them at: NROM and CNROM at 0x8000;
  MMC1, UxROM and UNROM 512 as 16 KiB banks with the last fixed at 0xC000 and the others at 0x8000; MMC3 as 8 KiB banks
  with the last two fixed at 0xC000 and 0xE000; AxROM and GxROM as 32 KiB banks at 0x8000. A mapper the app doesn't
  know is read like UxROM (the import says so). Which bank the CPU sees at a moment is decided by writes to mapper
  registers at run time, so this is the usual picture, not a promise. Names spell the bank and the address:
  `func_<bank>_<address>`.
- Functions are found from the **three vectors** (NMI, reset and IRQ, the last six bytes of the PRG) by following
  `jsr` and `jmp`, then `jsr` targets in code nothing reached, then tables of three or more addresses that each
  point at a function (also the address-minus-one form `rts` dispatch uses). **Not found:** code reached only through
  an indirect `jmp ($xxxx)`, through split high/low address tables, or by pushing an address and returning to it
  from computed values. Data inside a function's range is not told apart from code.

## The matching lane

Matching uses the pinned **GBDK-2020** toolchain: `sdcc -mmos6502` for C, `sdas6500` for assembly, the same archive as
the Game Boy and Master System. The app installs it when a game is imported. The ROM's call and jump addresses are
absolute, so the build pins every symbol to the ROM's own address and compares bytes directly, with nothing masked.
Until the toolchain is installed a `.nes` project is imported **read-only**: disassembled and searchable, but not
handed out for matching.

## What SDCC does on the 6502

- **Arguments:** the first byte argument is in A and the second in X; a 16-bit first argument is A (low) and X (high).
  Further arguments live in static RAM named `<function>_PARM_<n>`.
- **Results:** a byte comes back in A, a 16-bit value in A (low) and X (high).
- **Static memory:** the parameters above and any local SDCC cannot keep in registers are static variables the *linker*
  places (`_<function>_PARM_3`, `_<function>_<variable>_<n>_<n>`). The assembler counts them from zero, so a function that
  uses one differs from the ROM in that address operand and nothing else. Tell the build where the ROM keeps it with a
  comment anywhere in your source: `/* pin add3_PARM_3 = 0x0375 */`. Read the address off the target assembly (the
  `adc $0375` that your build shows as `adc $0000`). A name without the numbers the compiler appends matches too, and
  those numbers change with the code around them, so write `/* pin fill_v = 0x0378 */` for a local `v` of `fill`
  (`fill_sloc0` for the compiler's own temporaries). The compile output lists the variables it left at address 0.
  With every one pinned the function can match: a plain-C `fill` did, byte for byte, in testing.
- **Zero page:** the compiler's own registers (`DPTR`, `REGTEMP`, the return slots) are at $32, $34 and $3C onward in a
  GBDK-built game. A game built another way may keep them elsewhere, which shows as the same kind of operand difference.
- **Hardware:** the PPU registers are 0x2000-0x2007, the controllers 0x4016/0x4017, the APU 0x4000-0x4015.
  Write them as volatile pointers: `*(volatile u8 *)0x2000 = v;` is `sta $2000`.
- **Calls:** declare the target and call it by name (`void func_001_c357(void); … func_001_c357();`): the ROM's own
  address is substituted, so the `jsr` is byte-exact. A call in tail position becomes `jmp`.

## What moves SDCC's output

The lane is new, so this list is short on purpose. Add what you measure with `add_note` (no function name):

- A global at a fixed address is `__at(0x0365) u8 table[16];` (its accesses become `sta $0365,y`). A global the ROM
  keeps somewhere the project has a symbol for is declared `extern`; the build uses the symbol's address.
- Narrow types matter. `u8` locals and `int` truncate differently, and `int` is 16 bits here.
- New projects build with `--fsigned-char` and no optimization flag, which is what GBDK's own `lcc` does.

## Conventions

- Keep the split's `func_<bank>_<address>` names unless a function's purpose is clear.
- Helper types and prototypes that several functions share go in the project's shared header
  (`get_context`), never edited per function to force a match.
