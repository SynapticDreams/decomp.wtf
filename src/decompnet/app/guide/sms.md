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

Use **Preview profile and resplit** to analyze a proposed supported profile without saving it. **Apply profile and
resplit** commits that exact proposal, its layout and recovery history together. Editing any proposal field discards
the preview; work or input changes require another preview. All accepted source is checked in the proposed model,
including routines whose bytes and placement stay unchanged. Failed/unresolved source remains unaccepted and
recoverable through resplit history. Byte checks do not establish names or purposes; retained interpretation needs
review. Active claims and background analysis block apply. Undo checks restored accepted source and can refuse when
newer work or changed inputs prevent a safe restore; saved work remains available for forward recovery.
Ordinary **Save cartridge profile** still refuses mapping changes that would reinterpret accepted source. After
selecting mapperless directly, preview and apply a resplit if existing coordinates came from Sega paging;
source acceptance remains blocked while incompatible coordinates remain. The migration API is `/api/resplit` POST
with `profile: {mapper, variant, reason}`; applying also requires `apply: true` and the preview's `plan` fingerprint.

Resplit previews offer pages of changed routines, overlapping candidates and accepted source awaiting checks.
Pages contain at most 100 records; long display names are clipped with an explicit flag. They contain no source
bodies. Inspection recomputes the preview and checks its fingerprint, including any proposed profile; a changed
input, annotation, setting or proposal requires another preview. The operator API is `/api/resplit` POST with the
preview's `plan` and `inspection: {kind: "changed" | "checks", offset: 0}`; use kind `"overlaps"` with a saved
`function` ID for its candidate placements. Follow `inspection.next_offset` until null. Inspection cannot apply or
undo work and does not run source checks. Automatic checks on apply have a 32-function / 30-second budget;
exhausted checks leave source unresolved and unaccepted, available for manual validation through recovery.
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
removed named entries, unsupported mapping and unqualified compiler recipes remain unresolved and unaccepted.
The preview reports the number requiring checks; apply reports passed/failed/unresolved counts and bounded
metadata-only details. Configured compiler include trees are captured as described below; this does not establish
original toolchain identity, ABI correctness or linked replacement behavior.
Snapshot retention does not establish source validity under changed boundaries/context.
SMS classification, data changes and history are committed in one SQLite transaction, including rollback on
commit failure. Unchanged work and applicable claims remain attached to their original function rows; applying
changes to an actively claimed function requires releasing that claim first.

Configured include directories are captured privately before discovery/validation, preserving ordered overlays,
nested files, empty directories, read/write/execute permission bits, modification times, symlink aliases and
missing-directory state. Retained C using these inputs is
rechecked even when the function layout stays unchanged. The compiler receives materialized captured files;
it does not use live project includes for that validation. Source/target hashes bind the resplit result to the
specific checked text and bytes. A concurrent dependency edit invalidates apply, and a later edit blocks undo.
An existing entry retains its compiler unit, including named units and legacy project defaults, so later
ordinary judging selects the context that was validated. Stored unit headers still override copied context.h,
matching ordinary compilation. Additional include paths,
response files, external peephole files and unsupported compiler commands remain unqualified for automatic
revalidation. Full toolchain/ABI and linked replacement qualification is separate from these C-byte references.

Dependency capture is bounded to 32 MiB total, 4 MiB per file, 8,192 files, 16,384 traversal nodes, 64 roots,
64 levels and 1,024 recipes, within the existing snapshot encoding budget. Cyclic/unreadable trees and exhausted
budgets stop resplitting before work commits. Existing no-include records retain their snapshot digest format and remain eligible for guarded undo.
Older records with configured includes but no captured dependency contents remain inspectable; whole undo is
refused with a recovery message because their historical compiler inputs are unknown. Snapshot capture records
the context at resplit time and cannot retroactively establish the context of an earlier accepted attempt.
The archive's **Compiler dependency manifest** and selected **Dependency** items recover the captured tree/order.
UTF-8 text preserves original bytes; other files use base64 text with an explicit encoding and original content
SHA-256. These private dependency records are historical references, not a claim of prior acceptance validity.

**Resplit history** in Settings lists metadata in pages of 50. Undo restores the latest active snapshot only if
the current project work and inputs still match its recorded result. New notes, attempts, claims, annotations,
headers, settings or sidecar edits block undo; a saved ID reused outside the project is an explicit conflict.
Before restoring changed accepted source or interpretation context, undo checks the old target against the frozen
input and rejudges its source in the saved mapping, symbols, data and captured unit context, outside the database
transaction. Failed/unresolved source or exhausted source-check budgets refuse undo; the archive remains available.
Identical accepted work in an unchanged context can retain its acceptance. History records counts for the undo
checks, and source-check limits are shared with resplitting. Edits during these checks invalidate the final restore.
History remains available after a conflict. Repeated resplits undo in reverse order. Deleting a project removes
its private history. The operator API uses `/api/resplit` GET (`before` for pagination) and POST (`undo` with a
history ID); existing POST preview/apply calls remain available. History responses contain counts rather than
stored source. Each snapshot is bounded to 100,000 rows and 64 MiB of encoded work; sidecar verification is capped
at 64 MiB per file. Exceeding a budget stops the apply before it commits. Existing databases gain history storage
without rewriting existing work. This recovery path currently covers local SMS/GG projects.

**Browse saved work** in each history entry provides forward recovery when newer work blocks undo. It shows
saved function names, revision hashes, CPU/physical coordinates and target digests, then separately lists saved
accepted/best sources, attempts with their author IDs/scores/header versions, notes, headers, compiler settings,
symbols and review metadata. Old and undone snapshots remain inspectable. These are historical references;
copying or downloading them never changes current functions, accepted source, drafts, claims or annotations.
Review recovered text and submit it through the usual source checks against the current target/context.
The browser verifies complete text against its SHA-256 and character count before enabling copy/download.
A separate download includes the selected text and its snapshot/function/item provenance. The **Full saved
provenance** item recovers complete original metadata when a listing reports clipped fields.

**Saved project context** works even when the snapshot has no functions. It exposes project-owned notes, all
saved unit headers, corrections, data records, symbols, compiler settings and claims as historical references.
Notes with missing former functions keep that unknown association; projectless orphan references are never
assigned to a project. The selected **Saved compiler dependency bundle** contains the captured files and metadata;
binary content uses base64 in `$blob` objects, and capture does not establish their earlier acceptance context.
The project manifest includes declared input/profile identity and record counts, without dumping unrelated settings.
Nothing is restored or accepted by browsing, copying or downloading these records.

The private operator GET route is `/api/resplit/archive`, with `slug` and `history`. Without a `function` ID it
pages saved functions; with one it pages available `items`. Use `scope=project` to page project context instead;
it cannot be combined with a `function` ID. Select `project`,
`compiler`, `symbols`, `claims`, `dependencies`, or a listed `note:ID`, `header:VERSION`, `correction:ID` or
`data:OFFSET` item in that scope. Both scopes return at most 25 metadata entries per page, with
`next_offset` for subsequent requests and explicit clipping flags on long metadata strings. Selecting `item`
returns text, its SHA-256, character count and `next_start`; pass that as `start` until it is null. Offsets count
Unicode code points. Text chunks default to 16,384 characters and accept `limit` up to 262,144 (at most 1 MiB of
UTF-8 text, excluding JSON escaping/metadata). Lists contain no source bodies. Text recovery shares the 64 MiB
snapshot/text and 100,000-row budgets. Unknown projects, snapshots, functions or items, corrupt/over-budget
snapshots and invalid cursors fail visibly. This read-only API needs operator authentication; it is not a worker
tool or a way to accept archived source. Access to the current original input is not needed just to inspect history.

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
guide `asm`). The project's export is a WLA-DX disassembly made from the user's copy. It attempts to insert the
documented routines, reports omissions and checks the rebuilt image byte for byte.

## The matching lane

The Python splitter supports `sms.split(..., symbol_layout=declaration)` for explicit WLA source geometry.
Project imports also accept that declaration through `/api/symbols/import` POST's `layout` field. Send `text`
or `source_base64` (one source); the latter preserves exact original bytes, including BOM and line endings.
`apply: false` previews without writing files or changing project work. Pass its `plan` back as `expected_plan`
when applying to reject stale previews. Importing a declaration retains existing routine names and accepted
source; splitting again can use its qualified seeds and names for newly discovered routines.

New SMS/GG uploads without a layout retain records as `requires_layout` suggestions, with no effective names or
seeds. Settings provides source/layout selection, preview, application, stored inspection and disabling. It preserves
original file bytes through base64. Choose both files again to qualify or replace a stored source. Candidate names
and seed suggestions remain separate from names already assigned to existing routines and semantic approval.
Sources live in private immutable bundles selected by project metadata. The original comments and source paths
stay out of API reports. `/api/symbols/inspect` POST returns at most 50 records, with `next_offset`; send that as
`offset`, the current `source_id` as `expected_source` and `inspection_context` as `expected_context` to reject
source or mapper/project changes between pages. These fingerprints are required after the first page. Candidate
coordinates are bounded to 32 per record with an explicit truncation flag. Counts and source hashes remain visible.
Preview pages use `/api/symbols/import` with the same source/layout, `apply: false`, `offset` and `expected_plan`.
Both preview and stored pages reject changed context/source; a used or stale preview needs to be generated again.
Changed/missing bundles stop resplitting instead of falling back to another symbol file. Removing a source
disables it while retaining its private provenance; it does not activate an older adjacent file.

Initial import brings a bounded adjacent `.sym` and optional `.sym.layout.json` into the private project. A valid,
revision-bound declaration selects normalized seeds; absent or rejected declarations leave the source pending.
Malformed or wrong-revision sources retain their private bytes without contributing labels. The source view
shows rejected input/layout states and notices. Adjacent declarations are capped at 2 MiB.

Legacy project and direct-split `.sym` files also remain unqualified until explicitly declared. They cannot
silently reinterpret WLA bank IDs as physical banks. Use resplit preview to inspect affected entries and preserved
work before applying. Python `read_sym` requires `layout` and normalized `image` bytes for WLA records. Legacy
scripts that already assert physical code coordinates must opt into `physical=True`; the reader never assumes
that a WLA bank ID is a physical bank by default. Current discovery uses declared sources.
The version 1 declaration contains `input: {size, sha256}` for the normalized image, `banks` with
`{id, offset, size}` in physical file order, `slots` with `{id, start, size, space}`, and `views` with
`{bank, slot, offset, size, role}`. Bank sizes may differ; they must cover the image exactly once. A view's
offset is relative to its source bank and CPU slot, not to a hardware mapper bank. Spaces are `rom`, `ram`
or `unknown`; roles are `code`, `data` or `unknown`. All fields are required and integer values are decimal JSON
numbers. The declaration describes assembler placement rather than live hardware state.

Only declared code labels and automatic `_LABEL_<hex>_` markers in otherwise unknown ROM views become seed
suggestions. Data, RAM, local, impossible and conflicting records do not seed routines. Ordinary labels in unknown
views stay suggestions; automatic markers never supply semantic function names. `report.symbol_import` preserves
source hash, original label coordinates, normalized offsets, aliases and unresolved reasons. WLA ROM checksums,
when supplied, must match. Sources are bounded to 8 MiB, 250,000 lines and 100,000 records; declarations and normalization have
explicit bank/view/work budgets. A different revision or exhausted budget is refused.

This adapter follows the pinned [WLA symbol format](https://github.com/vhelin/wla-dx/blob/v10.7/doc/symbols.rst)
and [assembler bank/slot directives](https://github.com/vhelin/wla-dx/blob/v10.7/doc/asmdiv.rst).

Settings and Source show separate SMS/GG evidence dimensions. Physical byte totals use range unions, so aliases
or overlapping entries cannot inflate C-reference, documented-assembly, code or data totals. Code/data overlap
is reported explicitly; classified data is not automatically typed data. The C percentage covers C candidates,
with a bounded chart of current references by their stored acceptance dates, rather than overall game completion.
Score-closeness estimates remain instruction-weighted estimates. Neither metric establishes linked replacement.

The Source panel distinguishes current original-input readiness, the last build's whole-image equality, assembly
actually inserted, and omissions. **Require every expected documented assembly routine to be inserted** enables
strict mode; `/api/export` POST accepts the boolean `strict_documented` for SMS/GG. An omitted routine can make
strict verification fail even when the image is equal, while other actual insertions remain counted. Standalone
`python build.py --require-documented` applies the same policy. `build/verification.json` records process, input,
image and source results, including failed configuration/input/tool runs; console success words are not proof.

The overview API's `sms_progress` and `export.verification` separate these dimensions. Export summaries bound
visible omissions to 100 with a truncation flag; complete per-routine results stay in the exported report. Saved
results become historical after stored work/settings or exported inputs/results change. The current check compares
frozen input identity, project metadata and a bounded exported-tree fingerprint, excluding generated scratch files.
Fingerprinting caps reads at 64 MiB and 16,384 entries and refuses symlinks/special files. Unavailable evidence
cannot qualify a current result. Tool environment and external C dependencies are outside that cached check.
Unbound legacy inputs need a cartridge declaration to bind the revision before exact export can be verified.

Stored C references retain named-unit headers and compiler settings in `c/references.json`, with safe unit folders.
This export does not freshly compile or link them; context at export does not attest an earlier accepted attempt.
Typed data and semantic approval stay unqualified until their evidence schemas can establish them. An absent
review-sample flag is not proof that a person reviewed the current source/context. Runtime parity remains untested.

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

The synthetic assembly, migration and export checks run in the **SMS assembly** CI workflow with pinned WLA-DX
and GBDK. To run that gate locally, install `decompnet toolchain install wla-dx` and
`decompnet toolchain install gbdk-2020`, then run
`uv run python tools/sms_gate.py` from the repository. It checks SMS and GG exports and fails on missing
tools, failed comparisons or skipped tests. The default report is `build/sms-tool-tests.xml`.

- Keep the split's `func_<bank>_<address>` names unless a function's purpose is clear.
- Helper types and prototypes that several functions share go in the project's shared header
  (`get_context`), never edited per function to force a match.
