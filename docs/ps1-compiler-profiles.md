# PS1 compiler profiles

Project Settings → Compiler selects the project default or a source unit. A unit can override the compiler and
flags; **Use project default** removes its override. Existing matches in the affected units must still match
before a change is saved. Open functions keep their best source, but their scores and drafts are invalidated.

Imported PS1 overlays default to `-G0` when no explicit import flags were supplied. This is a starting point:
resident code and individual overlays may need different settings. Select the unit in Settings to adjust it.

The stored configuration has this shape:

```json
{
  "compiler": {
    "toolchain": "gcc-2.7.2-psx",
    "flags": ["-O2", "-G8"],
    "units": {
      "ovl_sample": {"flags": ["-O1", "-G0"]},
      "alternate": {"toolchain": "gcc-2.8.1-psx"}
    }
  }
}
```

An override inherits unspecified project settings. Selecting a different toolchain uses that toolchain's own
command and default flags unless the override supplies them. An empty flag list explicitly means no flags.
Signedness is selected with `-fsigned-char` or `-funsigned-char` in the unit's flags.

Attempts, batch builds, m2c drafts, the local permuter, donated jobs, context regression checks and MIPS exports
resolve settings using the function's source unit. A batch reuses compiled output only when its effective settings
and context agree. Exported `build.json` retains the profiles and each function's unit, including overlays that
share a load address. The generated build and single-function checks resolve the same profile.

The local HTTP API accepts `POST /api/compiler` with a project `slug`, `unit`, optional `toolchain` and optional
`flags`. Omitting both settings removes that unit's override. Omitting `unit` changes the project default while
retaining unit overrides. Forks use their existing project build scripts.

## Optional ASPSX emulation

The **Assembler** selector in PS1 project Settings enables maspsx for a selected ASPSX version. Install the pinned
`maspsx` and `binutils-mips` tools first. The bundled GNU assembler remains the default.

The profile field `"aspsx": "2.56"` selects that emulation; `"aspsx": ""` selects the bundled assembler, including
when overriding a project that uses maspsx. Unit profiles inherit this field like other settings. HTTP compiler
updates accept the same optional `aspsx` field. Omitting it retains the current selection.

The optional pipeline runs GCC with `-S`, processes the resulting assembly with maspsx and assembles it using the
pinned modern MIPS binutils. It enables division expansion and passes the compilation's last `-G` threshold to
maspsx. Every stage runs within the existing compilation sandbox, and a failed stage fails the build. Exported
builds and donated workers use the same driver and pinned tools.

ASPSX versions can produce different bytes for the same compiler output. For example, the regression fixtures
check constant loading across 2.21 and 2.56 and division guards across several versions. A version choice is a
matching hypothesis; the normal byte comparison remains authoritative.

## Compiler variants

The pinned compiler registry offers GCC 2.5.7, 2.6.0, 2.6.3, 2.7.2, 2.7.2 CDK, 2.8.0, 2.8.1, 2.91.66 and 2.95.2
for PS1. GCC 2.7.2 remains the initial default. Install alternatives in **Compilers & tools**, then select them
for the project or a source unit. All variants use the PS1 m2c draft target and support optional ASPSX emulation.

The additional compiler packs use verified Linux assets from decompals/old-gcc release 0.17 and pinned binutils
2.6. On Windows these Linux compilers run through the existing WSL integration.
