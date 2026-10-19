# SMS/GG annotation storage, version 1

The annotation foundation stores research metadata on existing corrections, symbols
and notes. It does not yet expose an editing API or consume these declarations for
discovery. Corrections with either metadata column populated are held out of legacy
split hints. The five existing correction kinds continue to work with NULL metadata.

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
Future mutation/consumption workflows must establish current project bindings and
operator authority before treating any receipt as acceptance.

## Bounds and compatibility

JSON is capped at 64 KiB, 4,096 value nodes and depth 16, with bounded strings and
exact-range integers. Duplicate keys, floats, booleans in integer fields, unknown
version 1 fields and malformed geometry are rejected. Each schema validates a
declaration; byte correspondence and semantic interpretation require qualified
consumers and evidence.

Opening a database atomically adds nullable `annotation` and `evidence` TEXT
columns to corrections, symbols and notes. Reopening is idempotent. Existing rows
retain NULL metadata: no provenance, context, confidence or approval is invented.
Non-NULL metadata survives snapshot/reload/undo byte for byte. NULL optional columns
are omitted from snapshot encoding to retain existing history hashes; restoring
old snapshots fills only those known optional columns with NULL. Missing required
columns and unknown future database columns still fail strict restore checks.
Export context fingerprints use the same NULL-field compatibility rule, preserving
an unchanged project's historical export context while detecting populated metadata.

The mandatory SMS gate executes schema, migration and real pinned-tool C/assembly
recovery fixtures on both SMS and GG. These checks qualify the storage foundation;
they do not claim structured discovery or a complete annotation editor.
