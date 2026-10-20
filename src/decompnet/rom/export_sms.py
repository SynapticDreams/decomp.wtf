"""Export a Master System or Game Gear project as a WLA-DX project that rebuilds the game byte for byte.

As the Game Boy's (export_gb.py): most of these games are assembly, so this is their source, the base for mods,
translations and ports. The tree holds the project's work, never the game's bytes: where each function starts, runs
and ends and its name (layout.json), what's known about each routine (comments.txt), the routines documented in
assembly (documented/, with names.inc for the names they use), the matched functions' C (c/, for reference), the
hardware's names (include/hardware.inc) and the Z80 disassembler (tools/z80.py, decomp.wtf's own). build.py makes the
disassembly from the user's copy (code as instructions, the rest as bytes, a label at every function and every jump
target), puts each documented routine in place of its bytes, assembles it with WLA-DX and checks it against the copy.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

from ..limits import capped
from . import sms, sms_asm, sms_hw
from .export_gb import NOTE_CHARS, NOTES_PER_LABEL, _documented
from .sms_identity import verify_normalized
from .sms_profile import describe
from .export_sms_verification import verify
from .export_sms_report import source_digest
from .export_sms_c import write as write_c
from .export_sms_artifacts import fingerprint as artifact_fingerprint, read_regular

LABEL = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")  # a name WLA-DX takes as a label
WORD = re.compile(r"(?<![.@\w])[A-Za-z_]\w*")
DOCUMENTED = "documented"


def export_sms(net, slug: str, out: Path, log=print, *, strict_documented=False) -> dict:
    proj = net._project(slug)
    cfg = net.cfg(proj)
    if cfg['rom'].get('identity') is None and not re.fullmatch(r'[0-9a-f]{40}', str(cfg['rom'].get('sha1') or '')):
        raise ValueError('frozen SMS/GG input identity is unavailable; declare a profile to bind this revision')
    rom_path = Path(proj["root"]) / cfg["rom"]["file"]
    raw, info = read_regular(rom_path, int(cfg['rom']['size']) + 513)
    if info.st_size > int(cfg['rom']['size']) + 512:
        raise ValueError('original SMS/GG input size differs')
    image = sms.strip_copier_header(raw)
    verify_normalized(image, cfg["rom"].get("identity"), cfg["rom"].get("sha1"))
    profile = describe(cfg)
    if profile["status"] == "invalid":
        raise ValueError(profile["message"])
    if out.exists():
        for child in out.iterdir():
            if child.name != ".git":
                shutil.rmtree(child) if child.is_dir() else child.unlink()
    out.mkdir(parents=True, exist_ok=True)
    platform = cfg.get("platform") or "sms"
    base = f"baserom.{'gg' if platform == 'gg' else 'sms'}"

    rows = net.store.all("SELECT * FROM functions WHERE project_id=? AND rom_offset IS NOT NULL ORDER BY rom_offset",
                         proj["id"])
    regions = net.store.all("SELECT * FROM data_regions WHERE project_id=? ORDER BY rom_offset", proj["id"])
    documented, left_out = _documented(net, proj, rows, log, judge=sms_asm)
    hw = set(sms_hw.names())
    named = [r for r in rows if LABEL.match(r["name"]) and r["name"] not in hw]
    named_ids, documented_ids = {r["id"] for r in named}, {r["id"] for r in documented}
    references = write_c(net, proj, out, [row for row in named if row['status'] == 'matched' and row['matched_source']])
    reference_paths = {row['name']: row['file'] for row in references}
    notes, matched = [], len(references)
    for r in named:
        why = json.loads(r["meta"] or "{}").get("asm_code") or ""
        said = [f"Set aside: {why}"] if why and r["status"] == "asm" else []
        if r['name'] in reference_paths:
            said.append(f"Stored C-byte reference: {reference_paths[r['name']]}")
        if r["id"] in documented_ids:
            said.append(f"Documented in assembly: {DOCUMENTED}/{r['name']}.asm (build.py puts it in place of its bytes)")
        for n in net.store.all("SELECT text FROM notes WHERE function_id=? ORDER BY id DESC LIMIT ?", r["id"], NOTES_PER_LABEL):
            text = " ".join(n["text"].split())
            said.append(text if len(text) <= NOTE_CHARS else text[:NOTE_CHARS - 3] + "...")
        notes += [f"{r['name']}: {line}" for text in said for line in textwrap.wrap(text, 110)]
    (out / "comments.txt").write_text("\n".join(notes) + ("\n" if notes else ""), encoding="utf-8")
    if matched:
        (out / "c" / "context.h").write_text(net._context(proj["id"])["header"] or '', encoding="utf-8", newline='')

    entries = _write_documented(net, proj, out, [r for r in documented if LABEL.match(r["name"])],
                                {r["name"] for r in named})
    omissions = dict(left_out)
    exported_names = {entry['name'] for entry in entries}
    expected = [{key: row[key] for key in ('name', 'size')} | {'flat': row['rom_offset'], 'cpu': row['vram'],
        'source_sha256': source_digest(row['matched_source'] or ''),
        'omission': omissions.get(row['name']) or ('source_not_exported' if row['name'] not in exported_names else None)}
        for row in rows if row['status'] == 'documented']
    banks = {int(s["rom_start"]) // sms.BANK_SIZE: int(s["vram"]) for s in cfg.get("segments") or []}
    layout = {"functions": [{"name": r["name"] if r["id"] in named_ids else None, "flat": r["rom_offset"], "cpu": r["vram"],
                             "size": r["size"]} for r in rows],
              "regions": [[r["rom_offset"], r["size"], r["kind"]] for r in regions],
              "banks": {str(b): v for b, v in sorted(banks.items())}, "documented": entries}
    (out / "layout.json").write_text(json.dumps(layout, indent=0), encoding="utf-8")
    (out / "include").mkdir(exist_ok=True)
    (out / "include" / "hardware.inc").write_text(
        "; The hardware's names (decomp.wtf's fixed set for the Master System and Game Gear: rom/sms_hw.py)\n"
        + sms_hw.inc(), encoding="utf-8")
    (out / "tools").mkdir(exist_ok=True)
    shutil.copyfile(Path(__file__).with_name("z80.py"), out / "tools" / "z80.py")
    shutil.copyfile(Path(__file__).with_name("sms_identity.py"), out / "tools" / "sms_identity.py")
    shutil.copyfile(Path(__file__).with_name("sms_mapping.py"), out / "tools" / "sms_mapping.py")
    shutil.copyfile(Path(__file__).with_name("sms_codemasters.py"), out / "tools" / "sms_codemasters.py")
    for source, target in (('export_sms_report.py', 'sms_export_report.py'), ('export_sms_build_run.py', 'sms_export_build_run.py'),
                           ('export_sms_artifacts.py', 'sms_export_artifacts.py')):
        shutil.copyfile(Path(__file__).with_name(source), out / 'tools' / target)
    (out / "build.json").write_text(json.dumps({"title": proj["name"], "platform": platform, "image": base,
                                                "sha1": hashlib.sha1(image).hexdigest(), "size": len(image),
                                                "identity": cfg["rom"].get("identity"),
                                                "sms_profile": profile, "expected_documented": expected,
                                                "c_reference": {"stored_matches": matched, "verified_by_build": False, "source_linked": False}},
                                               indent=1), encoding="utf-8")
    shutil.copyfile(Path(__file__).with_name("export_sms_build.py"), out / "build.py")
    (out / base).write_bytes(image)
    (out / ".gitignore").write_text(f"build/\n{base}\n__pycache__/\n", encoding="utf-8")
    _docs(out, proj["name"], base, matched, len(rows), len(entries))

    log("building the exported project to check it rebuilds the game byte for byte")
    input_artifacts = artifact_fingerprint(out)
    proc = subprocess.run(capped([sys.executable, "build.py", *(["--require-documented"] if strict_documented else [])]), cwd=out, capture_output=True, text=True, timeout=3600,
                          encoding="utf-8", errors="replace")
    result_artifacts = artifact_fingerprint(out, outputs=True)
    verification = verify(out, image, expected, proc.returncode, platform, required=strict_documented)
    verification['export_inputs_coherent'] = input_artifacts is not None and input_artifacts == artifact_fingerprint(out)
    if not verification['export_inputs_coherent']:
        verification['passed'] = False
        verification['errors'].append('export_inputs_changed_or_unavailable')
    final_artifacts = artifact_fingerprint(out, outputs=True)
    verification['export_outputs_coherent'] = result_artifacts is not None and result_artifacts == final_artifacts
    if not verification['export_outputs_coherent']:
        verification['passed'] = False
        verification['errors'].append('export_results_changed_or_unavailable')
    verification['export_tree_sha256'] = final_artifacts if verification['export_outputs_coherent'] else None
    identical = verification['passed']
    if not identical:
        log((proc.stdout + proc.stderr)[-3000:])
    receipt = verification.get('build') or {}
    source_receipt = receipt.get('documented')
    source_rows = source_receipt.get('routines', []) if isinstance(source_receipt, dict) else []
    if not isinstance(source_rows, list) or not all(isinstance(row, dict) and 'name' in row and 'omission' in row for row in source_rows):
        source_rows = []
    if not source_rows and expected:
        source_rows = [dict(row, inserted=False, omission=row.get('omission') or 'source_insertion_unverified') for row in expected]
    left_out = [(row['name'], row['omission']) for row in source_rows if not row.get('inserted')]
    if left_out:
        log(f"{len(left_out)} documented routines left as the disassembly has them: "
            + "; ".join(f"{n}: {why}" for n, why in left_out[:6]))
    return {"path": str(out), "identical": identical, "sms_profile": profile,
            "exact_original_intent": profile["exact_original_intent"], "verification": verification,
            "matched": matched, "functions": len(rows),
            "documented": sum(row.get("inserted") is True for row in source_rows) if verification["receipt_valid"] else 0,
            "left_out": left_out, "fallback": [], "log": (proc.stdout + proc.stderr)[-3000:]}


def _write_documented(net, proj, out: Path, rows, labels: set[str]) -> list[dict]:
    """documented/: each routine's text, and names.inc with the project's names they use that aren't labels in the
    build (RAM, constants)."""
    if not rows:
        return []
    (out / DOCUMENTED).mkdir()
    entries, used, own = [], set(), set()
    for r in rows:
        text = r["matched_source"].replace('\r\n', '\n').replace('\r', '\n').strip() + "\n"
        (out / DOCUMENTED / f"{r['name']}.asm").write_text(text, encoding="utf-8")
        entries.append({"name": r["name"], "flat": r["rom_offset"], "cpu": r["vram"], "size": r["size"],
                        "file": f"{DOCUMENTED}/{r['name']}.asm"})
        _items, found, _header, _problems = sms_asm.parse(text)
        own |= {name for _n, name in found if LABEL.match(name)}
        for line in text.splitlines():
            used |= set(WORD.findall(sms_asm._split_comment(line)[0]))
    names = {r["name"]: r["address"] for r in net.store.all(
        "SELECT name, address FROM symbols WHERE project_id=? AND address IS NOT NULL", proj["id"])}
    hw = set(sms_hw.names())
    defs = sorted((n, v) for n, v in names.items() if n in used and n not in labels and n not in own and n not in hw
                  and LABEL.match(n))
    (out / DOCUMENTED / "names.inc").write_text(
        "; The project's names the documented routines use that aren't labels in the build (RAM, constants, ...)\n"
        + "".join(f".DEFINE {n} ${v & 0xFFFF:04X}\n" for n, v in defs), encoding="utf-8")
    return entries


def _docs(out: Path, title: str, base: str, matched: int, total: int, documented: int) -> None:
    (out / "README.md").write_text(f"""# {title} (disassembly)

The game as WLA-DX assembly that rebuilds it byte for byte, with the names and notes worked out with
[decomp.wtf](https://decomp.wtf). Most Master System and Game Gear games were written in assembly: this is their
source, the base for mods, translations and ports. {documented} of the {total} functions found so far are documented
in assembly (in `documented/`), and {matched} have stored C-byte references (in `c/`).

## Build

1. Your own copy of the game is here as `{base}` (it is in `.gitignore`; never commit it).
2. `python build.py`: it makes the disassembly from your copy into `build/disassembly/` (code as instructions with
   the project's names, the rest as bytes, the notes in `comments.txt` as comments, each documented routine in place
   of its bytes), builds it with [WLA-DX](https://github.com/vhelin/wla-dx), and checks the result against your
   copy. Needs WLA-DX: decomp.wtf's pinned one when decomp.wtf is installed, else `wla-z80` and `wlalink` on `PATH`
   (or `WLA_DX` set to the folder that has them).

Build checks write `build/verification.json`: verified input identity, actual image digests/equality,
documented source emission/insertion and omission reasons, and process/policy results. `python build.py
--require-documented` fails if expected documented source is left out, even when raw reconstruction is identical.
`--no-documented` deliberately omits it. C remains reference material; this build does not link C replacements,
qualify typed data or semantic review, or test runtime parity. Console success words alone are not verification.

The build includes the same cartridge resolver as the application. A declared supported model and an emitted
instruction's CPU address can establish references within its own window; section placement does not establish
other mapped banks. Undeclared or unresolved references remain numeric. Matching the entire image verifies its
reconstruction independently of those mapping and naming limits.

## Layout

| Path | What it is |
| :-- | :-- |
| `layout.json` | Where each function starts, the address it runs at, its size and its name; what isn't code; where each bank runs. |
| `comments.txt` | What's known about each routine (`Name: text`), put above it in the disassembly. |
| `documented/` | Mechanically checked assembly with names, comments and constants. `build.py` attempts to insert each in place of its bytes and reports omissions; `names.inc` holds names they use that aren't labels. `python build.py --no-documented` builds without them. |
| `include/hardware.inc` | The hardware's names the documented routines use (ports, the mapper's registers). |
| `c/` | Stored C-byte references, not compiled or linked by this build. Each effective unit keeps its own header; `references.json` records context and compiler settings at export, without attesting prior acceptance or complete ABI/toolchain context. |
| `tools/`, `build.py`, `build.json` | Decoder, revision/mapper helpers, build orchestration, verification receipt and input manifest. |

`build/disassembly/` is made from your copy on every build, so keep your work in `layout.json`, `comments.txt` and
`documented/`. Memory operands in work RAM ($C000-$FFFB) are spelled by name in the same bytes: a name
`documented/names.inc` gives that address (when it gives exactly one), else `_RAM_XXXX_` from the generated
`ram.inc`. The Sega header's 16 bytes are written out as its fields. To change the game itself, copy `build/disassembly/` elsewhere and edit it there (`game.asm` is the
file to assemble); the header's checksum then needs updating, which WLA-DX's `.COMPUTESMSCHECKSUM` does.

The game's code and data belong to their rights holder, and the documented routines are its code written out:
keep this tree to yourself unless you have the right to share it.
""", encoding="utf-8")
