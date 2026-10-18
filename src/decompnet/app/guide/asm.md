# The assembly track: documenting a hand-written Game Boy routine

Most Game Boy games were written in assembly, so for most of a game there is no C to match. A routine the app set
aside as hand-written (status *assembly*, a reason such as "reads hl before setting it") is decompiled by
**documenting** it: RGBDS assembly that rebuilds its bytes exactly, with names, comments and constants where the ROM
has addresses. It's kept as the project's source for that routine and goes into the exported disassembly.

`claim_function(track="asm")` hands you the next one (the smallest first); one asked for by name that's on the track
comes on it too. Send the whole routine with `compile_and_diff(function, source)`. The answer lists every check it
still fails; accepted, the function is **documented** under its label's name.

## The six checks

1. **The same bytes.** It's assembled at the routine's address in its bank (rgbasm and rgblink, with hardware.inc
   6.0, its older names and the project's symbols already included). The answer shows the first instruction that
   differs, both ways.
2. **Every address is a name.** It's assembled again with the routine and every address the project knows moved:
   each call or jump target, memory operand, and 16-bit constant in ROM or RAM must move with it. Use the routine's
   own labels, the project's names (function names, names given with `rename_symbol`), or name an address yourself:
   `DEF wMenuOpen EQU $C0A2` (accepted, it becomes the project's). A 16-bit constant that isn't an address (a length,
   a count) is marked with a comment saying so: `ld bc, $0200 ; number: bytes to copy`.
3. **Banked code by the right name.** A call, jump or pointer into $4000-$7FFF names a function in the bank mapped
   there: the routine's own bank, or (from bank 0) the bank the split followed the call into (the brief lists them).
   Where banks share the address and no one knows which is mapped, it can't pass yet: say what you know with
   `correct_split`, or release it with a note.
4. **Instructions stay instructions.** `db` and `dw` only over the data the brief lists inside the routine (the bytes a
   routine reads after its call, a table) or an instruction a branch lands in the middle of.
5. **Hardware by name**, as hardware.inc 6.0 names it: `ldh [rLCDC], a`, `ld [rROMB0], a` (the bank register),
   `ld hl, TILEMAP0 + $21`, `ld de, _VRAM + $0800`. The older names (`rKEY1`, `rSVBK`, `LCDCF_ON`) work too.
6. **Real names, and a comment.** No automatic names (`Call_002_4a10`, `.l_4a20`, anything ending in an address):
   the routine's label says what it does, its local labels what they're for. Comment lines before the label say what
   it does, what it takes and what it returns, and which bank it maps if it maps one.

## Writing it

The brief has a **draft** that already rebuilds the bytes: the project's names filled in, hardware by name,
`db` over the data, a `.l_XXXX` label at each branch target. Start from it, or from the best attempt so far.

- RGBDS syntax: `ld a, [hl+]`, `ldh [c], a`, `ld hl, sp + 4`, `jr nz, .loop`, `rst $28`.
- One instruction a line; `db`/`dw` for data. Labels: `Name:` for the routine (and a second entry point), `.local:`
  inside it.
- What changes how the rest assembles, or reads files, is refused: INCLUDE, INCBIN, SECTION, MACRO, REPT, EQUS, OPT,
  IF and the like.
- Name what the routine touches from what it does with it: a byte it tests and branches on is a flag
  (`wMenuOpen`), a pointer it loads into HL a table (`MenuItemTable`). Read neighbours with `read_data` and the callers
  with the brief's notes; names the project already has carry over to every routine that uses them.
- A routine that turns out not to be one (data, two routines, half of one): `correct_split` or `flag_for_review`, as
  on the C track.
