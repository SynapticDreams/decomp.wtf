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
