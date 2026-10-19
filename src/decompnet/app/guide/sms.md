# Matching Sega Master System and Game Gear code

The Master System (SMS) and Game Gear (GG) run a **Zilog Z80**. capstone has no Z80 backend, so the fork
carries its own disassembler (`decompnet.rom.z80`), checked against SDCC's assembler on every instruction
encoding. Cartridge mapping and original compiler depend on the project; an SMS/GG extension does not establish them.

Choose the cartridge mapping and build intent in project Settings, with the evidence for that choice.
New imports and legacy projects with no declaration remain readable as provisional Sega-based listings;
accepting new C or documented assembly requires a supported declaration. Sega, mapperless and qualified Codemasters
models are supported under the static-analysis limits below and authored synthetic checks. Other mappings can be
recorded but remain unsupported. Mapperless inputs must fit within 48 KiB; undeclared
small-ROM mirroring remains unresolved. A declaration does not establish hardware accuracy.
Codemasters qualification currently covers power-of-two inputs from 32 to 512 KiB and canonical writes to
$0000/$4000/$8000. All three windows page, including the first KiB; the selected reset recipe is 0/1/0.
[SMS Power](https://www.smspower.org/Development/Mappers) describes mirrored writes throughout each window;
[Gearsystem](https://github.com/drhelius/Gearsystem/blob/master/src/CodemastersMemoryRule.cpp) decodes canonical
addresses and separately gates cartridge RAM. Noncanonical ROM writes therefore invalidate the affected selector
and report unqualified mirror decoding. A set/unknown slot-1 high bit leaves $A000–$BFFF unresolved without RAM-wiring
evidence; $8000–$9FFF remains ROM. Clearing the flag restores ROM selection. Effective source knowledge and raw
selector values remain separate. Codemasters selectors have write-only names; reads there name ROM, not a latch.
The hardware include retains existing Sega aliases for stored source, while new drafts use the selected model.

Settings offers **Inspect mapper evidence** (also `/api/sms/profile` GET). This scans at most 64 KiB for possible
absolute-store byte patterns and returns at most 32 records with ROM offsets, scan/record truncation and candidates.
Suggestions always have low confidence and remain ambiguous: patterns may occur in data or patched code, and size
or absent patterns prove no mapper. They never change the declaration, acceptance gate or revision identity.
Missing/changed input makes suggestions unavailable. Use independent wiring evidence for profile selection.

Profile changes retain existing work and refuse mapping changes that would reinterpret accepted source.
After selecting mapperless, preview and apply a resplit if existing function coordinates came from Sega paging;
source acceptance remains blocked while any such incompatible coordinates remain.
Experimental build intent is recorded separately from original reconstruction; whole-image equality still
compares against the frozen original input. The local operator API is `/api/sms/profile` (GET or POST).

Reference resolution distinguishes CPU addresses from cartridge offsets. An established code entry identifies
its own mapped window; its display placement does not establish banks in other windows. Only Sega's first KiB
is fixed to bank 0. Mapper-register reads see work RAM, including its mirror: writing the other RAM alias can
change that readback without selecting a new bank. Reset register values are a selected analysis recipe,
not a guarantee for every mapper revision. The tracer carries full bus snapshots through calls and tables,
and joins incoming mapping facts conservatively. Known mapper-control writes update RAM selection; a bank change
updates the next instruction's source. The reset root uses an explicit cartridge-only recipe. Isolated seeds
establish only their own ROM window. Entry/reset/register facts come from the selected model. Mapperless wiring
has no selector/control latches. Reset facts apply to the actual CPU-zero reset-vector root; a symbol at CPU zero
or ROM offset zero running in another window does not imply reset. A matching entry correction preserves reset.
Distinct register, RAM, stack and mapper facts at the same instruction are followed separately.
Each function has instruction, per-address context, stack and sparse-memory budgets;
unchanged loops converge as table/bound marks age and expire. Exhausted entries appear in split logs and the
`analysis_exhausted` report/resplit result with their ROM offsets and reasons. Their discovered callees retain
only conditional entry-window facts; exhausted analysis cannot prove a mapper helper or a nonreturning routine.
Physical stack accesses and interrupt restoration remain analysis limits; this does not qualify
BIOS, cartridge-RAM or peripheral execution, or establish complete discovery when no budget was exhausted.
Control knowledge is tracked per bit: a Sega ROM entry in slot 2 establishes that RAM is deselected there, without inventing
shift/write-enable bits or raw register latches. Joins keep agreed bits even when another control bit differs.
Explicit byte/word stores, memory read-modify-write operations, block transfers/input and possible memory-control
port writes now invalidate affected facts. Word stores apply both bytes in CPU order, including address wrap;
RAM aliases still do not select a mapper bank. An unknown destination discards sparse RAM and virtual-stack values.
Known VDP/PSG/I/O-control output ports preserve mapping; unknown outputs and possible memory-control mirrors
leave bus sources unresolved. Hardware/mode-specific port enable values are not interpreted as a new mapping.
An explicit SP is tracked through ordinary pushes, pops and calls. Known physical stack accesses require
unambiguous work RAM away from mapper registers; active stack aliases, including RAM mirrors, are guarded
within a 512-byte window. Writes into that active storage, unqualified destinations and tracking exhaustion
stop interpretation with a reason. Pushes discard stale sparse-RAM facts at their destinations; pushed physical
bytes are not supplied as new RAM-readback values. Unknown SP keeps an explicitly conditional ordinary virtual-stack
contract; this does not qualify all physical stack placement, asynchronous writes or interrupt interleaving.
Explicit SP changes discard saved virtual values; popping an untracked index register still consumes its value.
Saved register widths are retained: A alone does not establish a full AF return address, pair-to-AF pops use
the high byte for A, and unknown saved flag bytes cannot justify a comparison bound.
Ordinary callees are evaluated with actual incoming registers, mapping and sparse RAM. Conditional calls include
the uncalled path, and returned mapping/RAM facts are joined across all known return paths. Evaluation has a shared
2,048-instruction budget across nested calls, depth limit eight and per-address/stack/memory limits. Unknown sources,
unqualified writes or returns, SP changes, interrupt returns, EI/HALT and exhausted budgets leave caller effects
unresolved. `analysis_unresolved` reports caller entry offsets and reasons in split logs and resplit results.
Computed continuations with known pushed addresses and declared inline-return adjustments use the same evaluator.
EI and interrupt returns are reported as unqualified boundaries on directly followed paths as well as in callees.
HALT stops discovery until a wake-up context is qualified. An interrupted save/change/restore sequence therefore
remains conditional, even when its uninterrupted stack/bank restoration can be followed. DI does not establish
NMI preservation. Assembly references after these boundaries or SP relocation remain pending without a contract.
Known nested call targets are retained as conditional static discovery evidence even when another path is unresolved;
they do not establish a complete target set or execution observations.
Whole-discovery accounting is shared across retracing passes: at most 4,000 distinct physical/CPU entries,
1,000,000 followed instructions including 262,144 callee instructions, and 64 tracer rounds by default.
Each tracer additionally needs convergence within eight rounds; gap discovery has eight passes. Exhausting
these bounds, dropping excess entry seeds or truncating candidate output is disclosed in `analysis_limits`,
with configured limits, usage and reasons. Partial discovered entries remain available, with conditional
entry-window facts instead of complete incoming mapping claims. `analysis_exhausted` also marks affected entries.
Instruction counters cover tracing/evaluation; cold scans keep their separate input-size and extent bounds.
Function-entry back-edges revisit changed path facts without replaying reset state; unchanged loops converge.
A run within budget remains heuristic and subject to unqualified sources and execution-coverage limits.
The resplit preview includes these diagnostics before work is applied.
Resplit verifies the normalized input against the frozen revision before and after discovery, and again around
database updates. Legacy SHA-1 identities and equivalent recognized copier wrappers remain usable. A missing,
malformed or changed identity stops the operation; profile or other project settings edited during analysis require a retry.
If an input change is detected during database updates, that transaction rolls back.
SMS/GG previews also identify changed work and overlapping candidates (at most 100 changed entries and eight
overlaps per entry, with total counts and truncation disclosed). Settings sends the preview fingerprint when
applying; changed work, annotations, sidecar inputs or candidate layout require a new preview. Direct operator
API calls can omit that optional fingerprint and analyze the current state. Concurrent edits during discovery
or before mutation still stop the apply.

An SMS/GG apply saves a private, versioned snapshot of its configuration, functions, attempts, claims, notes,
symbols, corrections, data regions and context headers. New candidates never reuse deleted function IDs, and
removed attempts are retained in the snapshot. Changed SMS/GG layouts no longer protect old matched-C ranges
from the splitter. Accepted C and assembly are checked against the proposed entry, bytes, symbols, CPU placement,
data map and stored unit header before opening the database transaction. Concurrent edits invalidate the result.
A passing assembly check establishes byte/placement validity under the declared model; a passing C check is a
function-byte reference under the current compiler/context. Neither proves original compiler identity, linked
replacement behavior, ABI correctness or semantic purpose. Retained semantic interpretation needs review.
Failed or unresolved source remains an unaccepted draft at the same physical entry when available; otherwise
it remains in history. Old attempts and scores stay with their original target. Applicable names and review
metadata survive; documented source is returned to the review sample. Revalidation checks at most 32 functions,
64 KiB per source, with a 30-second batch budget and bounded individual tool runs. Exhausted checks, missing tools,
removed named entries, unsupported mapping and external compiler includes remain unresolved and unaccepted.
The preview reports the number requiring checks; apply reports passed/failed/unresolved counts and bounded
metadata-only details. External include dependency capture and forward recovery from history remain pending.
Snapshot retention does not establish source validity under changed boundaries/context.
SMS classification, data changes and history are committed in one SQLite transaction, including rollback on
commit failure. Unchanged work and applicable claims remain attached to their original function rows; applying
changes to an actively claimed function requires releasing that claim first.

**Resplit history** in Settings lists metadata in pages of 50. Undo restores the latest active snapshot only if
the current project work and inputs still match its recorded result. New notes, attempts, claims, annotations,
headers, settings or sidecar edits block undo; a saved ID reused outside the project is an explicit conflict.
History remains available after a conflict. Repeated resplits undo in reverse order. Deleting a project removes
its private history. The operator API uses `/api/resplit` GET (`before` for pagination) and POST (`undo` with a
history ID); existing POST preview/apply calls remain available. History responses contain counts rather than
stored source. Each snapshot is bounded to 100,000 rows and 64 MiB of encoded work; sidecar verification is capped
at 64 MiB per file. Exceeding a budget stops the apply before it commits. Existing databases gain history storage
without rewriting existing work. This recovery path currently covers local SMS/GG projects.
Explicit nonreturn corrections apply; an incomplete trace never supplies a preserving or nonreturning contract.
This remains static analysis under an ordinary virtual-stack contract; asynchronous interrupt preservation,
physical byte/flag stack emulation and complete execution qualification remain pending. Neither adapter is a CPU emulator.
Instruction forms follow the [Zilog Z80 manual](https://www.zilog.com/docs/z80/um0080.pdf); source-selection
limits follow the [memory-control reference](https://www.smspower.org/Development/Port3E) and
[hardware notes](https://github.com/drhelius/Gearsystem/blob/master/skills/gearsystem-debugging/references/smstech.md).
Standalone exports include this shared resolver. Generated reference names require a declared model and established
instruction geometry; unresolved references remain numeric while the build still verifies whole-image equality.
Assembly judging uses the same source/bank resolver. A unique routine name at a CPU address cannot establish its
physical bank, including slot 0 above the first KiB. Unknown references stay pending. Known stores invalidate
affected entry-bank facts conservatively. Assembly routine records do not supply callee bodies or return contracts;
references following a call remain numeric/pending rather than inheriting its entry-bank facts. Tracer evaluation
does not silently become an assembly acceptance contract. Stored source is retained if revalidation reports an omission.

## What the importer does with a .sms / .gg file

- A Sega header is recognised by content: `TMR SEGA` at 0x7FF0 (0x3FF0 or 0x1FF0 in a ROM of 16 or 8 KiB).
  Its last byte gives the region (Master System or Game Gear) and the size. A ROM with no header is still
  taken when it is named `.sms` or `.gg` and has a plausible size. A 512-byte copier header is dropped.
  The project retains SHA-256 identities for the supplied dump and normalized ROM, including any removed header.
  Reimporting the same revision with another wrapper adds input evidence. Export refuses changed comparison
  bytes before replacing existing output; headerless inputs keep product/revision unknown.
- ROM offsets are grouped into **16 KiB banks**. Sega fixes only the first KiB to bank 0; writes to 0xFFFD,
  0xFFFE and 0xFFFF select the larger CPU windows, with RAM selected through mapper control. Mapperless wiring is
  flat within its supplied bytes. Names spell the physical bank and declared/discovered CPU coordinate:
  `func_<bank>_<address>`. Display placement for an unresolved bank is provisional.
- Functions are found from the reset vector, the RST handlers and the NMI by following calls, tail jumps, bank
  switchers and the tables dispatchers read (`ld hl,table / jp dispatch`, or a function's own
  `ld hl,table / add hl,de / ... / jp (hl)`, as many entries as a `cp n / jr nc` before it allows), plus a sweep for
  `call`s in the banks that hold code and code that starts right where a function ends. The following also keeps
  slot 0 paged by 0xFFFD, a bank kept in RAM or saved on the stack and mapped again, and a computed call
  (`ld de,.next / push de / jp (hl)`), which comes back to `.next`. A symbol file next to the ROM names functions,
  and its automatic `_LABEL_..._` names say where code starts. Code reached only through pointers kept in RAM may
  still be missing, and data inside a function's range is not told apart from code.
- When the split took data for code, missed a function, or decoded the bytes after a call as instructions, say so
  with `correct_split(kind, at, reason, count)`, with how you know (what reads it, what calls it, what it holds):
  `data` (`count` bytes at `at` aren't code), `code` (a function starts at `at`), `table` (`count` handler
  addresses at `at`), `operands` (the routine at `at` reads `count` bytes after each call to it and returns past
  them), `noreturn` (it never returns). `at` is a function's name, `NN:AAAA` (the bank and the address it runs at,
  `05:8123` for bank 5 in slot 2) or an address in `function`'s bank. It's used the next time a person splits the
  game again (they can undo it first); ten an hour at most. Table corrections retain their explicit CPU window.
  An unqualified SMS address resolves only with established window evidence; use `NN:AAAA` or a function
  name when a bank is required. A unique function at a CPU address is insufficient mapping evidence.
- A person can also import what an emulator saw while they played (Settings, a Mesen2 code/data log or a
  `bank:address` trace): splitting the game again then starts functions where calls entered and where code ran that
  wasn't reached, and keeps what was only read as data out of functions.
  SMS/GG text traces describe physical cartridge-ROM banks and CPU instruction addresses. Declare Sega or mapperless
  mapping in Settings before interpreting them; RAM/BIOS execution needs a richer format. Invalid coordinates and
  explicit gaps break entry evidence. Entry candidates require adjacent call/target records; a target appearing
  elsewhere in the log is insufficient. Observed CPU windows are retained, including paged slot 0; multiple windows
  for one physical entry remain ambiguous. The format has no session identity or loss accounting, so it does not
  establish a complete capture. A failed import retains the previous file. Byte-indexed code/data logs remain
  readable without a mapper declaration.
  A Sega code/data log supplies physical ROM offsets without CPU windows. New placements need a symbol, an
  explicit entry correction or another established CPU context; section defaults cannot fill that gap.

- The import reads which toolchain built the game: GBDK-2020's start-up code (C), or an SDSC tag (homebrew,
  not which tool). A game none of them built is most likely assembly, for the assembly track.

## Hand-written routines

Most Master System and Game Gear games are assembly. A routine set aside as hand-written is documented instead of
matched: WLA-DX assembly that rebuilds its bytes, with names, comments and constants (`claim_function(track="asm")`,
guide `asm`). The project's export is a WLA-DX disassembly made from the user's copy, with each documented routine
in place of its bytes, checked to rebuild the game byte for byte.

## The matching lane

Matching uses the pinned **GBDK-2020** toolchain: `sdcc -mz80` for C, `sdasz80` for assembly, the same
archive as the Game Boy. The app installs it when a game is imported. The ROM's call and jump addresses are absolute, so the
build pins every symbol to the ROM's own address and compares bytes directly, with nothing masked.

Until the toolchain is installed a `.sms`/`.gg` project is imported **read-only**: disassembled and
searchable, but not handed out for matching, because no candidate could be judged.

## What's set aside

Most Master System and Game Gear games are hand-written assembly. The app sets aside what its split hands out that no C function is (status *assembly* or *not code*,
with the reason): pieces of a routine that run on into the next function (the split starts a function wherever code
jumps or branches to, and hand-written code branches into the middle of its routines), bytes that are no
instruction, `halt` (inline assembly only), padding, and a stretch the split ran its longest on. If a function you're given looks like one of
those, say so in a note and release it. `__naked` is refused: it leaves out the function's return, so it can only
reproduce such a piece, and a match has to be a whole function from C.

The split's boundaries can be wrong both ways. When a function you're given is two routines (one ends, the next
starts), `split_function(function, at=<CPU address where the second starts>)` cuts it. When it's half of one (it runs
on into the next function or jumps into it, or the one before runs on into it, and nothing else calls the second
half), `merge_function(function)` joins them. Each piece is checked again for what's set aside.

## What SDCC does on the Z80 (`sdcccall(1)`)

- **Arguments:** the first byte argument is in A and the second in L. 16-bit arguments are in HL, then DE.
  A 16-bit argument that follows a byte one is in DE. Further arguments go on the stack, and the callee
  pops them (`pop hl … jp (hl)` is how SDCC returns from such a function).
- **Results:** a byte comes back in A, a 16-bit value in **DE** (`add hl, de` then `ex de, hl`).
- **Ports:** declare them as `__sfr __at(0xBF) VDP_CTRL;`. Writing one is `out ($bf), a`, reading is
  `in a, ($be)`. The VDP is at ports 0xBE (data) and 0xBF (control), the controllers are read at 0xDC and 0xDD.
- **Memory:** a fixed RAM address is `*(volatile u8 *)0xC000`, which is `ld ($c000), a` / `ld a, ($c000)`.
  RAM is 0xC000-0xDFFF (mirrored at 0xE000); the mapper registers are 0xFFFC-0xFFFF.
- **`rst` calls:** `void func_000_0028(void) __z88dk_shortcall(0x28, 0);` then `func_000_0028();` builds to `rst $28` followed by
  the byte `0x00` (the second number is the byte that follows). Declare the function with its own name, as the project knows it.
- **Calls:** a call in tail position becomes `jp`. If the target has `call f` then `ret`, give the call
  something to do afterwards (a statement after it, or return a value) to get the `call`.

## What moves SDCC's output

The lane is new, so this list is short on purpose. Add what you measure with `add_note` (no function
name) so the next session starts ahead:

- Local declaration order and first use change register allocation: reorder before rewriting.
- Narrow types matter. `u8`/`s8` locals and `int` truncate differently, and `int` is 16 bits here.
- New projects build with `--fsigned-char` and no optimization flag, which is what GBDK's own `lcc` does. A game built
  another way may need `--opt-code-size` or `--opt-code-speed` (the project's compiler flags): if a loop or a jump comes
  out as `jp` where the target has `jr`, try those before rewriting, and say what worked in a note.

## Conventions

The synthetic assembly and export checks run in the **SMS assembly** CI workflow with the pinned WLA-DX.
To run that gate locally, install `decompnet toolchain install wla-dx`, then run
`uv run python tools/sms_gate.py` from the repository. It checks SMS and GG exports and fails on missing
tools, failed comparisons or skipped tests. The default report is `build/sms-tool-tests.xml`.

- Keep the split's `func_<bank>_<address>` names unless a function's purpose is clear.
- Helper types and prototypes that several functions share go in the project's shared header
  (`get_context`), never edited per function to force a match.
