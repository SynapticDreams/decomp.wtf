# SMS/GG annotation storage, version 1

Versioned research metadata uses existing corrections, symbols and notes. Bound
SMS/GG correction proposals now support preview, storage, inspection, operator
review and undo. The five existing untagged correction kinds keep their historical
meaning, with unknown provenance. New structured facts are pending by default.
Only current, operator-reviewed facts of those five kinds feed existing split hints.
Other structured kinds remain stored research until their discovery consumers are
qualified. Notes and symbols now support the same guarded metadata workflow. The
structured authoring/review UI is available in project Settings.

## Operator UI

In Settings, **Research and split corrections** switches between corrections,
notes/archives and existing symbols. Lists show 50 records per page. Select a
record to inspect its geometry, evidence links, alternatives, confidence, original
subject and review authority. Unsupported or malformed metadata stays readable as
bounded original text; clipped output is labelled. Evidence references are shown
as text and are never fetched automatically.

**New proposal** offers all ten declaration kinds, editable address space,
offset/extent and layout JSON examples. Examples describe geometry rather than
observed contents. Notes and symbols also allow evidence-only research without a
typed range. Legacy correction kinds need an explicit CPU placement; physical ROM
offsets remain separate. Alternatives use one line each; evidence links use a JSON
array. The editor rejects duplicate JSON keys and inexact integers before preview.
The server still validates every declaration, binding and protected source range.

**Preview proposal** shows the proposed research. **Apply** publishes exactly that
preview. Draft edits, subject/project switches and declared mapping/input changes
discard the preview; intervening work is also checked by the server. Pending
publication locks the draft. Failed/stale application requires a new preview.
**Discard draft** clears the proposal/preview without changing stored research.

Current supported subjects offer separate approval/rejection previews. The
inspection's review-authority status is distinct from the receipt claimed inside
stored JSON. Notes/symbols remain research after approval; new structured correction
kinds await qualified consumers. **Edit metadata** preserves existing note prose
and attachment. **Preview metadata detachment** preserves that prose/symbol and
archives its old metadata. **Copy to new proposal** creates fresh pending evidence
with fresh bindings, never transferring origin or approval; review any copied
interpretation and select a new note's attachment explicitly. Archives are read-only.
**Undo correction** keeps the existing history record and disables its hint.

Other platforms and room guests retain their existing workflows. UI qualification
uses authored fixtures over the real authenticated HTTP routes for both SMS and GG;
`uv run python tools/sms_ui_gate.py` requires a real Chrome/Chromium browser, Node and zero
skipped required checks. Tool versions are printed with its result.

## Correction workflow

`correct_split` keeps the existing kind/location/reason/count call. Counts must be
integers; extents must fit the ROM. New writes cannot classify accepted C or
documented assembly as data, split a verified entry internally, or alter its call
continuation contract. Existing untagged hints may describe inline data already
present when source was accepted; they retain their prior behavior.

For a bound SMS/GG proposal, pass `apply=false`. Existing five-kind arguments are
converted to a version 1 annotation, or supply an `annotation` object and optional
`evidence` object. Kind must agree with the annotation; omit legacy count when
providing explicit geometry. Correction targets are ROM; RAM declarations belong
on notes/symbols. Legacy hint kinds still need an explicit function or `NN:AAAA`
coordinate. New record/pointer kinds can identify physical ROM without inventing
a CPU window. Forced numeric values must match the original bytes.

The preview returns `plan` and the proposed `correction`. Apply the same arguments
with `apply=true, expected_plan=plan`. Missing/stale previews fail. The server binds
revision, declared mapping/source context and a digest of annotation, CPU placement
and target bytes. It derives agent origin, rejects supplied reviewed receipts and
sets review pending. Mutable work has a separate guard so a saved fact does not
invalidate its own stable binding. Bounds, revision/context mismatches, intervening
edits, changed inputs and publication failures cannot partially publish a fact.

`inspect_corrections` pages existing records (`limit`, `before_id`), or returns full
geometry/evidence for `correction_id`. HTTP uses the existing `/api/corrections`
GET endpoint with optional `id`, `before_id` and `limit`. Responses distinguish
legacy, pending, stale, unavailable, unsupported, invalid, rejected, conflict,
untrusted review and awaiting-consumer states. Unsupported/invalid raw metadata
remains stored verbatim; oversized malformed inspection output is explicitly clipped.

Operator POST `/api/corrections` accepts action `create` (the same preview/apply
arguments), `inspect` (`id`), or `review` (`id`, boolean `ok`, `apply`,
`expected_plan`). Review itself requires preview then exact application. The app's
operator cookie and write header guard these routes. Workers have no review tool.
Approval is bound to the exact stored row through the latest operator review event;
a JSON receipt, copied receipt or superseded approval cannot grant authority. Row,
binding and work reads use one database snapshot. `/api/corrections/undo` retains
the fact and evidence while disabling it; undo requires a positive integer `id`.

## Notes and symbols

`add_note` keeps existing text-only calls. For bound SMS/GG metadata, supply
`annotation` and/or `evidence` and preview with `apply=false`, then apply with the
returned `expected_plan`. Evidence-only prose notes need no artificial ROM range.
An optional `note_id` attaches/replaces metadata on existing immutable note text;
changing text or attachment requires a new note. Text is bounded to 4,000 characters.
`annotate_symbol(symbol, ...)` uses the same metadata/preview fields on an existing
exact symbol name. It does not rename the symbol or approve its purpose.

`inspect_annotations(kind="note"|"symbol", key=...)` returns full bounded evidence
and the original subject descriptor. Omit key to page: `next_before`/`before_id`
for notes, `next_symbol`/`after_symbol` for symbols. Page sizes are 1–100. Note keys
are positive integer IDs; symbol keys are exact bounded names.

The descriptor records original text or symbol identity, function attachment and
stored-target digest, normalized revision, declared mapping, source identity and
typed-target correspondence. ROM ranges include the original byte digest; RAM
declarations explicitly say contents are unobserved. They establish no runtime
value, mapping selection or lifetime. Caller receipts cannot grant review. Research
on notes/symbols always has `discovery=false`, including operator-reviewed research.

Operator HTTP uses `/api/note` and `/api/symbols/annotation` GET/POST. GET accepts
`id` (notes) or `symbol` (symbols), plus their page cursor and `limit`. POST actions
are `create`/`annotate`, `inspect`, `review` and `clear`. Review uses boolean `ok`;
review/clear require preview then exact application with `apply`/`expected_plan`.
Cookie and write-header guards are the same as corrections. Workers have no review
or clear tool. Legacy POST `/api/note` still returns its plaintext confirmation.

Replacing metadata resets review to pending and retains the prior metadata plus
descriptor as an explicitly inactive archive note. Clear detaches metadata while
preserving the note text or symbol and its archived original research; it does not
delete that prose or rename the symbol. It can detach unsupported metadata without
requiring the original input to be present, but still requires the exact work guard.
Archives are read-only research subjects and can be inspected for forward recovery.

Symbol refreshes preserve exact metadata for unchanged identity/extent/role.
Renames, size/role changes, merges and resplits archive original research before
changing or removing its subject; approval never transfers to a new name or range.
Original descriptors remain understandable after the function itself changes.
Local SMS/GG renames reject intervening work during source regression checks.
Agent briefs mark pending/stale research and omit archives from current context;
search returns an inactive archive reference rather than promoting its old prose.

Research context binds verified symbol-source bytes and bundle identity, excluding
upload timestamps/display names. Missing or changed bundles make bindings
unavailable; changed source bytes require new review. Context identity does not
replace the WLA adapter's separate layout/record qualification.

`decompnet.rom.annotations` provides `validate_annotation(value, rom_size=...)`,
`validate_evidence(value)`, bounded canonical `dump(value)` and
`inspect(raw, validator, **context)`. Inspection returns the original raw value and
one of `legacy_unknown`, `supported`, `unsupported_version` or `invalid`. Only
`supported` includes a parsed value. That status describes supported shape; it
establishes neither truth nor approval. Unsupported and invalid records remain
stored verbatim and inactive.

## Annotation envelope

Every version 1 object has exactly `version`, `kind`, `target` and `spec`. Targets
contain `space` (`rom`, `wram` or `cart_ram`), byte `offset` and positive `size`.
ROM offsets are physical normalized image offsets; RAM offsets are relative to
their separate address spaces. These declarations do not infer CPU placement,
RAM lifetime or runtime mapping. ROM bounds come from the caller's image size;
WRAM and cartridge RAM are bounded to 8 KiB and 32 KiB respectively. Those maximum
extents do not establish that a particular hardware profile exposes the memory.

| Kind | Specification |
| --- | --- |
| `code`, `noreturn` | Empty object; target identifies one entry byte |
| `data` | `encoding`: bytes, ascii, u8, s8, u16le or u16be |
| `table` | `count`: 1–128 dense words; target size is twice count |
| `operands` | Callee entry target; `bytes_after_call`: 1–8 |
| `record` | `count`, `stride`, `fields`, `overlap`: reject or views |
| `pointers` | `count`, `stride`, `pointer_offset`, `encoding`: u16le/u16be, `bank`, `target`: code/data/unknown |
| `split_pointers` | `count`, `stride`, `low_offset`, `high_offset`, `bank`, `target`: code/data/unknown |
| `number` | `value` and `endian`: little/big, occupying 1–4 bytes |
| `mapping` | `when` and `facts` using explicit shared bus-state fields, scoped to a ROM range |

Record fields have a unique identifier `name`, `offset` within the stride, and
`type`. Scalar types are u8/s8 and signed/unsigned 16/32-bit little/big endian.
`bytes` adds `width`; `bits` adds storage `width` (1, 2 or 4), `endian`, and a
`bits` array of unique `{name, lsb, width}` items. `ptr16le`/`ptr16be` add `bank`
and `target`. Field extents and bit positions must fit; overlapping fields require
explicit `views`. Padding remains unspecified, rather than becoming typed data.

A pointer's `bank` is NULL for a near pointer, or an object with `offset`, `width`
(1–2), `meaning` (physical/register/assembler) and `source_sha256`. Assembler bank
identifiers require a source-layout hash; the other meanings require NULL there.
This preserves the distinction between physical, register and assembler bank IDs;
it does not resolve a pointer. Bank offsets are relative to each record for
records/pointers, and identify a parallel strided bank array for split pointers.
Low, high and bank arrays must be in bounds and disjoint. A numeric literal never
implicitly becomes a pointer.

Counts are bounded to 4,096 and strides to 65,536 bytes. Scoped mapping objects
accept only `banks`, `registers`, `control`, `control_known`, `cartridge`, `bios`,
`wram`, `other_source` and `rom_modified`, checked by the shared `BusState` model.
Their presence records a claim; no mapping declaration updates the live bus.

## Evidence envelope

Evidence has exactly `version`, `revision`, `context`, `subject_sha256`, `origin`,
`state`, `confidence`, `alternatives`, `links` and `review`.

Revision is NULL or `{platform, size, sha256}` for sms/gg normalized input.
Context is NULL or `{mapper, sha256}` for sega/mapperless/codemasters. Subject is
NULL or a SHA-256 digest. All hashes use lowercase hexadecimal. The storage layer
does not establish correspondence between these claims and a current project.

Origin is NULL or `{kind, ref}`, with kind legacy/operator/agent/import/analysis/
session. Evidence states are unknown, observation, static_derivation,
interpretation and hypothesis. Confidence is independently unknown/low/medium/high;
unknown evidence requires unknown confidence. There are at most eight alternatives
and 16 links. Each link contains `{kind, ref, sha256}`; kinds are source/note/
analysis/session/external. Observation, static derivation and interpretation require
a link, but a link alone does not verify the claim. External references must be
HTTP(S) without embedded credentials; parsing never fetches them.

Review contains `state`, `actor`, `at` and `binding_sha256`. Unknown/pending states
require NULL receipt fields. Accepted/rejected shapes require revision, context
and subject plus a receipt bound to their canonical digest. A caller can compute
that digest, so passing shape validation does **not** authenticate a review.
The correction workflow establishes current project bindings and operator-event
authority before treating a receipt as acceptance. Schema validation alone does not.

## Bounds and compatibility

JSON is capped at 64 KiB, 4,096 value nodes and depth 16, with bounded strings and
exact-range integers. Duplicate keys, floats, booleans in integer fields, unknown
version 1 fields and malformed geometry are rejected. Each schema validates a
declaration; byte correspondence and semantic interpretation require qualified
consumers and evidence.

Opening a database atomically adds nullable `annotation` and `evidence` TEXT
columns to corrections, symbols and notes. Reopening is idempotent. Existing rows
retain NULL metadata: no provenance, context, confidence or approval is invented.
Notes and symbols additionally have nullable `subject` TEXT for the original
descriptor. Old metadata without a descriptor stays unbound; no descriptor is
inferred from its claims. Corrections retain their existing payload-based binding.
Non-NULL metadata survives snapshot/reload/undo byte for byte. NULL optional columns
are omitted from snapshot encoding to retain existing history hashes; restoring
old snapshots fills only those known optional columns with NULL. Missing required
columns and unknown future database columns still fail strict restore checks.
Export context fingerprints use the same NULL-field compatibility rule, preserving
an unchanged project's historical export context while detecting populated metadata.

The mandatory SMS gate executes schema, migration, authority and real pinned-tool
C/assembly recovery fixtures on both SMS and GG, including note/symbol lifecycle
and declared-source integration. Structured table discovery and a complete
annotation editor remain separate work.
