# Master System and Game Gear: research and improvement map

This note surveys public tools, references and community practice for Sega Master System (SMS),
Game Gear (GG) and SG-1000 work, and compares them with the current SMS/GG lane. It is a planning
document. Nothing here changes behavior, and the proposals still need their own design and checks.

Sources were read in October 2026. Claims marked *(unverified)* come from search summaries of pages
that could not be fetched directly; check them against the page before relying on them. Community
disassemblies of individual games are described by pattern rather than linked, following the public
content rules in `AGENTS.md`.

## Where the lane stands

The SMS/GG lane is unusually strong on provenance:

- revision-bound inputs;
- declared cartridge models (Sega, mapperless, qualified Codemasters);
- bounded static tracing with full bus snapshots;
- guarded resplits with history and undo;
- revision-bound WLA symbol import;
- reviewed research annotations;
- exports that are verified from receipts.

Its gaps are mostly about what it can *observe* and what it can *produce*:

| Area | Current state | Main limit |
| --- | --- | --- |
| Runtime evidence | Mesen2 CDLv2 or headerless code/data logs; text `bank:address` traces | No RAM or BIOS execution, no session identity, no CPU windows from a CDL (`src/decompnet/rom/coverage.py`, `src/decompnet/rom/sms_coverage.py`) |
| Runtime parity | Not tested (`runtime_parity: not_tested`) | No emulator integration |
| Mapper models | `sega`, `mapperless`, `codemasters` (`src/decompnet/rom/sms_profile.py:10-12`) | Korean, MSX/Nemesis, 4 PAK, Janggun, EEPROM and SG-1000 boards are record-only or absent |
| Mapper evidence | Operator declaration and low-confidence store-pattern scan | No hash database lookup |
| Data | Annotation schemas exist but are stored research; export emits raw `.db` | No graphics, tilemap, compression or sound recognition |
| Export shape | One `FORCE` section per bank at `.ORG $0000`; memory operands and 16-bit immediates numeric | Not shiftable; RAM is not named |
| Inline operands | Operator corrections only; `takes_return` is recorded but never consumed (`src/decompnet/rom/sms_trace.py:219`) | The GB tracer already detects inline shapes automatically (`src/decompnet/rom/gb_trace.py:417`, `:719`) |
| Toolchain detection | GBDK-2020 crt0 and the SDSC tag (`src/decompnet/rom/fingerprint.py:81-89`) | No devkitSMS, z88dk or library signatures; one GBDK `--fsigned-char` profile |
| CI coverage | `tools/sms_gate.py` runs the pinned WLA-DX/GBDK suites | `tests/test_z80.py` (sdasz80 round-trip) and `tests/test_sms.py` (SDCC matching) are not in the gate's list, and the main workflow has no toolchains, so they skip |

## Findings

### 1. Emulators as evidence and parity oracles

**Gearsystem** ([repository](https://github.com/drhelius/Gearsystem), GPL-3.0, active in October 2026):

- **MCP server.** Includes a documented `--headless` mode
  ([MCP_README](https://github.com/drhelius/Gearsystem/blob/master/MCP_README.md)). It covers
  stepping, frame stepping, breakpoints, memory reads and writes, disassembly, symbol loading,
  trace logging, profiling, screenshots, save states and controller input. One headless instance
  can run per HTTP port.
- **Trace logger.** CPU lines carry `bank:pc`, and separate events record mapper writes and port
  `$3E` memory control. Execution at or above `$C000` reports bank 0, so RAM and BIOS context has
  to be rebuilt from those events.
- **Mappers.** Supports Korean, MSX/Nemesis, Janggun and 93C46 EEPROM boards.
- **Hardware notes.** The guide already cites its notes.

**Mesen2** was archived in June 2026. Development continues as
[MesenCE](https://github.com/nesdev-org/MesenCE) (GPL-3.0).

- **CDL.** Its SMS code/data log is `CDLv2`, then a ROM CRC32, then one flag byte per ROM byte. It
  logs only cartridge ROM. This is the format the lane already reads.
- **Headless Lua.** `--testRunner` runs a Lua script headless. The script API can:
  - register execution and memory callbacks;
  - convert addresses to an absolute address plus a memory type (`SmsPrgRom`, `SmsWorkRam`,
    `SmsCartRam`, `SmsBootRom`);
  - read the CDL and the frame buffer;
  - save and load state.

  A small exporter script could produce the richer trace the guide says is missing: physical
  address, memory type, CPU address and frame number for ROM, RAM and BIOS execution. *(Not checked:
  whether MesenCE's API still matches Mesen2's.)*

**MAME** (`hash/sms.xml`, `gamegear.xml`, `sg1000.xml`, and the `sega8` cartridge bus):

- **Headless.** Runs with `-video none -nothrottle -str N`, Lua and debugger scripts.
- **Mapper reference.** Its slot devices are the most complete reference implementation of the
  boards we do not model: 4 PAK, Janggun, Korean variants, Zemina, Nemesis, multicarts and EEPROM.
- **WLA-DX symbol bridge.** `wlalink -E` exports debugger symbol files for MAME, Mesen and
  Emulicious, plus JSON ([wlalink manual](https://github.com/vhelin/wla-dx/blob/master/doc/man/wlalink.rst)).
  An exported project could hand emulators named symbols at no extra cost.

**Other emulators:**

- **Emulicious** is closed-source and GUI-driven. Its disassembler emits WLA-DX source, and its
  `_LABEL_xxx_` / `_DATA_xxx_` / `_RAM_xxx_` names are common in community projects. Use it only
  for manual cross-checks.
- **ares** traces only 16-bit addresses, with no bank.
- **Genesis Plus GX** has a broad mapper table but a non-commercial license, so neither its code
  nor its data should be vendored.

**Runtime-parity precedent.** One public SMS project keeps a WLA-DX disassembly that rebuilds
byte-identical, and generates a C translation from it. Its "shadow" mode runs each rewritten
routine, rewinds, runs the original on an interpreter, and reports differences in memory, video,
sound or registers. Headless runs print a final state hash. This is the runtime-parity shape this
lane lacks.

### 2. Static analysis and annotation models

- **[SkoolKit](https://github.com/skoolkid/skoolkit)** (GPL-3.0, ZX Spectrum) is the most mature
  design reference for annotated Z80 disassembly. Of interest:
  - Its control files use one-letter block types, sub-block lengths and comments.
  - `sna2ctl -m` builds a control file from an emulator code map.
  - `skool2ctl` round-trips a hand-edited listing back to a control file without losing annotations.
  - Fix directives (`@ofix`/`@bfix`/`@rfix`) build a byte-exact original and a corrected variant
    from one source.

  These ideas carry over to the annotation lane without taking a dependency.
- **[z80dismblr/DeZog](https://github.com/maziac/DeZog)** (MIT) gives two ideas:
  - fall-through subroutine splitting with call references;
  - per-routine complexity and call graphs, which suit agent briefs.

  Its bank hook only runs on `OUT`, so it cannot model Sega's memory-mapped registers.
- **[smstool](https://github.com/hansbonini/smstool)** (GPL-2.0) is a splat-style segment splitter
  driven by a YAML file.
- **Decompilers.** Ghidra ships Z80 SLEIGH. Its compiler spec has no `sdcccall` prototype, and bank
  overlays cannot resolve operands across banks
  ([discussion 9349](https://github.com/NationalSecurityAgency/ghidra/discussions/9349)).
  `pypcode` exposes the same SLEIGH lifter to Python. It could help value-set analysis of `jp (hl)`
  targets, but its C output is a hint, not matching source. Reko and Binary Ninja have Z80 lifters;
  none has a bank-aware SMS loader.
- **decomp.me** has no Z80 or SDCC compiler. We found no public byte-matching Z80 C decompilation.

### 3. Community disassembly practice

Public WLA-DX disassemblies converge on a few habits:

- **Build gate.** A one-command build checks the output hash and exits non-zero on mismatch, with
  WLA-DX pinned in CI. Several projects pin v10.7, the version this repository pins.
- **Several revisions from one source.** Revisions build from one tree with `-D` flags and one link
  file per revision.
- **Headers isolated in the memory map.** A separate slot covers the Sega header at `$7FF0` (16
  bytes), or the Codemasters header at `$7FE0` (32 bytes). The checksum comes from
  `.COMPUTESMSCHECKSUM`, or from `.SMSHEADER` with forced values when the original checksum is wrong
  ([WLA-DX directives](https://github.com/vhelin/wla-dx/blob/master/doc/asmdiv.rst)).
- **Sections.** `FORCE` sections hold byte-matching builds. `FREE`/`SUPERFREE` sections and
  `.BACKGROUND`/`.UNBACKGROUND` support patched or shiftable builds.
- **Data as files.** Graphics, tilemaps, palettes and sound live as per-asset `.bin` files. PNG
  round-trips through BMP2Tile only for uncompressed tiles. Compressed blobs stay verbatim unless a
  bit-identical recompressor exists. One project keeps RLE streams as symbolic `.db` control bytes.
- **Per-block checks.** One project verifies routines rewritten in a higher-level language by
  hashing their byte ranges, not the whole image. This matches this repository's per-function C lane.
- **Duplicate routines.** Byte-identical copies of a routine are common, and projects mark them
  explicitly.
- **Symbol banks.** Hand-written link scripts sometimes post-process `.sym` files because slot-1
  labels got the wrong bank. Generated symbol output should be correct per bank.
- **No ROMs in repositories.** The cleanest projects keep only code, names and notes, and take
  assets from a user-supplied ROM identified by hash. Two well-known projects commit the ROM; do not
  follow them.

### 4. Hardware, BIOS and header facts

- **BIOS entry state.** Maxim's
  [SMS/GG BIOS disassemblies](https://github.com/maxim-zhao/smsbioses) show what the BIOS leaves
  at cartridge entry:
  - **SMS BIOS:** stores the chosen port `$3E` value at `$C000` (`$AB` for a cartridge) before
    jumping to `$0000`.
  - **GG BIOS:**
    - pages slots 0/1/2 to banks 0/1/2, with cartridge RAM off;
    - clears `$C000-$DFEF` and sets SP to `$DFF0`;
    - writes `$A8` to `$C000` and port `$3E`, then jumps to `$0000`.

  These are candidates for named, selectable reset recipes ("SMS BIOS 1.3 entry", "GG BIOS
  entry"). The current single cartridge-only recipe would remain the default.
- **Game Gear ports.** Ports `$00`-`$06` are GG registers in GG mode: Start button and region at
  `$00`, link at `$01`-`$05`, PSG stereo at `$06`. `src/decompnet/rom/sms_effects.py:65` treats any
  output port with `(port & 0xC1) == 0` as a possible `$3E` memory-control mirror, which includes
  these ports. On GG projects, `out ($06),a` therefore discarded mapping facts. Gearsystem and MAME
  agree that `$00`-`$06` never reach memory control in GG mode, but disagree about mirrors at
  `$08`-`$3C`, so only `$00`-`$06` are exempted now. A GG cartridge with an SMS header runs in SMS
  mode and is already classified as `sms`.
- **Header quirks.** *(unverified)* Japanese and GG ROMs often carry wrong checksums. The size code
  often understates the real ROM size, and some early ROMs have no header. The SDSC tag and the
  Codemasters header both live at `$7FE0`, so detection must tell them apart.

### 5. ROM databases as mapper evidence

| Source | License | Content |
| --- | --- | --- |
| [MAME softlists](https://github.com/mamedev/mame/tree/master/hash) `sms.xml`, `gamegear.xml`, `sg1000.xml` | CC0-1.0 (stated in the files) | CRC32/SHA-1 per dump; `slot` feature (`codemasters`, `korean`, `korean_nb`, `zemina`, `hicom`, `nemesis`, `janggun`, `4pak`, …; GG `eeprom`; SG-1000 board types) |
| [MEKA `meka.nam`](https://github.com/ocornut/meka/blob/master/meka/meka.nam) | Permissive with attribution (`meka/sources.txt`) | CRC32 → `EMU_MAPPER` (130 entries), product number, country, flags such as SMS-mode GG games, plus notes such as wrong checksums |
| Gearsystem `game_db.h` | GPL-3.0 | CRC → mapper and feature flags |
| Genesis Plus GX `sms_cart.c` | Non-commercial | CRC → mapper and peripherals; reference only |
| No-Intro | Terms not verified | Hashes only, no mapper |

A hash match is independent evidence of a board, which the store-pattern scan cannot provide. It
fits the existing **Inspect mapper evidence** contract: it suggests and never declares. The MEKA
autodetect heuristic counts `ld (nnnn),a` writes to each mapper's registers in the first 32 KiB. It
corroborates the existing pattern scan.

### 6. Toolchains and C

- **Commercial C is unproven.** No commercial SMS/GG/SG-1000 game was confirmed to be compiled
  from C. Documented commercial tooling is assemblers: PDS, in-house assemblers, in-circuit
  emulators. The documented-assembly lane remains the main path for commercial work.
- **Homebrew C is the C lane's real audience,** and its toolchains have clear fingerprints:
  - **[devkitSMS](https://github.com/sverx/devkitSMS) `crt0_sms`:**
    - starts `di; im 1; ld sp,$DFF0`;
    - RST `$08`/`$18` write to the VDP;
    - embeds the ASCII string `devkitSMS`;
    - clears RAM while preserving `$C000`.

    `makesms` fills with `$00`, rounds to 16 KiB and packs SDSC strings backwards from `$7FE0`. Its
    builds use unsigned `char` (no `--fsigned-char`), often `--max-allocs-per-node 100000`, and
    their own peephole rules. SMSlib and PSGlib are C, and prebuilt `.lib` files are committed to
    its history.
  - **GBDK-2020 crt0:**
    - RST `$10`/`$20`/`$30` (`$30` is `jp (hl)`);
    - `.init` at `$80`;
    - `makebin -xj 6` gives GG region nibble 6, where devkitSMS uses 7.

    SMS/GG support started in 4.0.5, and each release ships its own patched SDCC build.
  - **z88dk classic crt0:** `jp` at `$0000` and an embedded `Z88DK` string; it also offers an older
    SMSlib copy.
  - **SDSC tags do not imply C.** WLA-DX emits them for assembly projects too.
- **SDCC version matters:**
  - `sdcccall(1)` became the Z80 default in 4.2.0 (2022).
  - 4.4.0 and 4.6.0 (2026-06) changed Z80 code generation substantially.
  - Peephole rules still change between snapshots.
  - Call shapes are cheap convention and era detectors: helper calls with register operands or
    stacked operands, and `___sdcc_enter_ix` calls or the inline IX prologue.
- **No public Z80 library signature sets exist.** Signatures could be built from published library
  objects: SMSlib/PSGlib per devkitSMS commit, GBDK libraries per release, and SDCC `device/lib/z80`
  per release. The `ar`-format `.lib` files contain relocatable `.rel` objects, so relocations can be
  masked like the PS1 signature format.
- **Ground truth.** Homebrew with both C source and released binaries gives ground truth for C
  matching and fingerprinting:
  - SMS Power competition entries, whose pages often state the compiler version;
  - devkitSMS-based repositories.

  Keep any corpus manifest to URL, commit, binary hash and toolchain version; do not vendor binaries
  or third-party sources.

### 7. Data formats

- **Compression codecs.** [bmp2tilecompressors](https://github.com/maxim-zhao/bmp2tilecompressors)
  catalogs SMS-era tile codecs with Z80 decompressors:
  - several game-family RLE and LZ variants, including the widely reused bitplane-interleaved RLE;
  - generic codecs common in homebrew: aPLib, ZX7, ZX0, LZ4, LZSA, Pletter, Exomizer.
- **Decompressor fingerprints.** Recognizing a known decompressor routine marks its input pointers
  as compressed data with a typed encoding. This is the qualified "discovery consumer" the
  annotation schema is waiting for.
- **Sound.** Sound drivers are a second signature family: Sega's SMPS ancestors, Compile's GG
  engine, and PSGlib in homebrew.

## Improvement map

Ordered by value for the effort and by how well each item fits the existing evidence model.

### Near term (small, contained)

Items 1-5 are implemented. Inline operands are inferred from the existing callee evaluator (every
evaluated return lands the same distance past the call) rather than ported from the GB shape matcher.

1. **Gate the existing Z80 and SDCC suites.** Add `tests/test_z80.py` and `tests/test_sms.py` to
   `tools/sms_gate.py`'s list, so the sdasz80 round-trip and SDCC matching checks run with pinned
   tools.
2. **GG port handling.** Do not treat `$00`-`$06` as possible `$3E` mirrors on projects declared as
   GG mode. Make GG-in-SMS-mode an explicit declaration, since a `.gg` file with an SMS header
   currently becomes `sms`.
3. **Automatic inline operands.** Consume `takes_return` the way the GB tracer does, for
   `rst`/`call` routines that pop their return address and read a table. Present the result as
   conditional seeds, as corrections are presented now.
4. **Toolchain fingerprints.** Add devkitSMS, GBDK (with GG region nibble), z88dk and WLA-DX
   (`SDSC`-only) detectors to `fingerprint.py`. Report an SDSC tag alone as "not evidence of C".
5. **Doc fix.** `guide/sms.md` says traces need Sega or mapperless, but the reader also accepts
   Codemasters.

### Medium term

Status of this group:

- **6: done for MAME.** The CC0 SMS/GG lists are extracted by `tools/sms_softlist.py`, keeping hashes,
  board and `pin_42`/`battery` features only. The MEKA extract was not added.
- **7: partly done.** Gearsystem trace logs are read directly, with port `$3E` tracking. The
  versioned JSONL session format and a MesenCE producer remain open: neither could be run against a
  real emulator here.
- **8: partly done.** RAM operands now have names, and header fields are spelled out; the build
  already wrote a `.sym` file. `.dw` tables and the shiftability check remain open.
- **9: deferred.** No discovery consumer gains from BIOS-left RAM values yet. Port `$3E` writes stay
  unresolved whatever their value.
- **10: partly done.** devkitSMS projects start without `--fsigned-char`. A multi-version SDCC
  matrix remains open.

6. **Hash-database mapper evidence.** Ship a CC0 extract of the MAME softlists, plus an optional
   attributed MEKA extract, keyed by normalized-ROM CRC32/SHA-1. Show board, slot feature and notes
   under **Inspect mapper evidence**. It suggests only, like the existing scan.
7. **Richer trace import.** Define a versioned JSONL trace with:
   - session identity and loss accounting;
   - memory type, physical offset, CPU address and frame;
   - call/return and mapper/`$3E` events.

   Ship producers for MesenCE (Lua `--testRunner`) and Gearsystem (headless MCP trace). This
   addresses the documented gaps: RAM/BIOS execution, CPU windows from CDLs, and capture
   completeness.
8. **Export quality.**
   - Isolate the header slot.
   - Name RAM and hardware operands from a generated `ram.inc`/`hw.inc`.
   - Emit word tables as `.dw` labels where entries are established.
   - Add an optional `wlalink -E` symbol export for emulators.
   - Add a "shiftability" check that rebuilds with deliberate padding and verifies every
     established reference moves. The assembly judge's ±`$10` shift test already does this per
     routine.
9. **BIOS-aware reset recipes** taken from the BIOS disassemblies, as declared, selectable analysis
   recipes.
10. **SDCC profile matrix for homebrew.** Add devkitSMS-style profiles (unsigned `char`,
    `--max-allocs-per-node`, custom peephole files) and selectable SDCC versions (pre-4.2
    `sdcccall(0)`, 4.2-4.5, 4.6). Allow these as project compiler settings, captured in resplit
    dependency snapshots.

### Longer term

11. **Runtime parity.** Drive original and rebuilt images through identical inputs in a headless
    emulator: Gearsystem MCP, MesenCE `--testRunner`, or MAME. Compare per-frame frame-buffer
    hashes, RAM snapshots and save states. Record the result as a separate evidence dimension next
    to whole-image equality. This only matters once builds can differ from the original (shiftable
    or modified builds), but it also turns "runtime parity remains untested" into a measured claim.
12. **Additional mapper models.** Implement 4 PAK, the Korean variants, MSX/Nemesis and Janggun,
    using MAME's `sega8` slot devices and the SMS Power mapper page as references. Use hash-database
    hits to find test candidates. Add SG-1000/SC-3000 boards after that.
13. **Library and driver signatures.** Build per-version signature sets for SDCC runtime helpers,
    SMSlib, PSGlib and GBDK libraries, then sound drivers. Exclude matched library code from agent
    work, as the PS1 signatures do.
14. **Data recognition.** Recognize known decompressors. Type their input regions with the existing
    annotation schema's encodings, and export assets as files with a hash check, falling back to
    verbatim bytes.
15. **Validation fixtures with source.** Rebuild these as end-to-end fixtures with known code/data
    boundaries:
    - [zexall-sms](https://github.com/maxim-zhao/zexall-sms);
    - the [BIOS disassemblies](https://github.com/maxim-zhao/smsbioses);
    - SMS/VDP test ROMs.

    Unlike the current synthetic ROMs, they exercise real program structure, including a routine
    copied to RAM.

## Licensing notes

- **Emulators as external programs.** GPL emulators (Gearsystem, MesenCE, MAME) should run as
  separately installed programs, as WLA-DX does, not be vendored into this repository.
- **Database data.** MAME softlist data is CC0. MEKA's data permits reuse with its notice. Genesis
  Plus GX data must not be reused.
- **AI-use requests.** At least one community disassembly asks not to be used with AI assistants.
  Respect such requests and use only its public description, not its contents.
