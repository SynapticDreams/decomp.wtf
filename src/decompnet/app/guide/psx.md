# Matching PlayStation (PS1) code

CPU: MIPS R3000A (MIPS I). Things that look odd at first:
- Load delay slot: the instruction after a load can't use the loaded value; you'll see `nop`s or
  reordering there. Branch delay slots exist too; there's no branch-likely.
- `mult`/`div` put results in HI/LO (`mflo`, `mfhi`). Division is followed by checks for divide by zero
  (`break 7`) and overflow (`break 6`): the PSY-Q assembler adds them. The bundled GNU assembler also
  emits these checks. Projects can optionally select maspsx emulation of a specific ASPSX version;
  the function brief identifies it when enabled. Write a plain `/`.
- `$gp`-relative small data (-G4 or -G8): small globals are read with `lw $v0, %gp_rel(sym)($gp)`
  (one instruction) instead of `lui` + `lw`. In a ROM project, declare such globals in context.h
  *without* `extern` (`s32 D_8001B278;`): the compiler then treats them as small data. With `extern`
  it builds the full address and the function won't match. Arrays and structs larger than the limit
  are never gp-relative.

Compilers: PSY-Q SDK GCC 2.6/2.7.2/2.8.x and ASPSX versions differ in register allocation and
instruction scheduling; the project picks them per file. Code is mostly C.

Libraries: PSY-Q's libgte, libgpu, libgs, libspu, libcd, libetc, libapi and libc are usually linked
as library objects, not decompiled; their names and prototypes are in the project's headers.

GTE (the geometry coprocessor): pinned PS1 profiles supply trusted `gte_*` macros automatically. New ROM
contexts also have `SVECTOR`, `VECTOR`, `DVECTOR`, `CVECTOR`, `RECT` and `MATRIX` declarations.

- `gte_ldv0(p)`, `gte_ldv1(p)`, `gte_ldv2(p)` load vectors; `gte_ldv3(p0,p1,p2)` loads three.
- `gte_rtps()`, `gte_rtpt()`, `gte_nclip()` and other lowercase command helpers include two preceding nops.
  Rabbitizer-style `gte_nRTPS()` has the same padding; `gte_RTPS()` emits just the command.
- `gte_stsxy(p)`, `gte_stsxy3(p0,p1,p2)`, `gte_stsz(p)`, `gte_stotz(p)` and `gte_strgb(p)` store results.
- `gte_mfc2(reg)` / `gte_cfc2(reg)` read a register; `gte_mtc2(reg,value)` / `gte_ctc2(reg,value)` write it.
  Register indices are masked to 0..31. Reads include a nop for the CPU load delay.
- `gte_mvmva(sf,mx,v,cv,lm)` has bounded immediate fields; its arguments must be compile-time constants.
  `gte_sqr(sf)`, `gte_op(sf)`, `gte_gpf(sf)` and `gte_gpl(sf)` cover the other parameterized commands.

Memory helpers use memory clobbers, which can affect scheduling and register allocation. The selected assembler
also affects scheduling: compare the emitted bytes, including nops. m2c may not produce a draft for COP2 code;
use the assembly and these helpers. Source and context edits cannot contain raw assembly or redefine the
trusted macros. Recognized library routines stay set aside.

Encoding and timing reference: [PSX-SPX GTE](https://psx-spx.consoledev.net/geometrytransformationenginegte/).
The command-name/opcode table follows Rabbitizer's MIT-licensed GTE macros; its notice is retained in the header.

Typical patterns: `jtbl_` jump tables in .rodata for dense switches; overlays loaded at the same address
(separate units); `D_800xxxxx` data and `func_800xxxxx` names for things nobody named yet.
