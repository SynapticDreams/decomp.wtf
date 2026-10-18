"""Export a Game Boy project as an RGBDS project that rebuilds the game byte for byte.

Most Game Boy games are assembly, so this is the base for mods, translations and any port: the disassembly with
the project's names and what its agents found out, rebuilt with RGBDS and checked against the user's copy. The tree
holds only the project's work (baserom.sym: names and padding, for mgbdis; comments.txt; the matched functions' C
in c/, for reference). The disassembly itself is made from the user's copy by build.py and stays out of git.
"""

from __future__ import annotations

import bisect
import hashlib
import json
import re
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

from ..limits import capped
from ..network import NetworkError
from . import sm83
from .gb import BANK_SIZE
from .gb_mgbdis import labels
from .n64 import RomError

LABEL = re.compile(r"^[A-Za-z_][\w@#$]*$")  # an RGBDS label (no dot: that's a local one)
NOTES_PER_LABEL, NOTE_CHARS = 2, 400


def export_gb(net, slug: str, out: Path, log=print) -> dict:
    proj = net._project(slug)
    cfg = net.cfg(proj)
    rom = Path(proj["root"]) / cfg["rom"]["file"]
    image = rom.read_bytes()
    if out.exists():
        for child in out.iterdir():
            if child.name != ".git":
                shutil.rmtree(child) if child.is_dir() else child.unlink()
    out.mkdir(parents=True, exist_ok=True)
    base = f"baserom{rom.suffix if rom.suffix in ('.gb', '.gbc') else '.gbc'}"

    rows = net.store.all("SELECT * FROM functions WHERE project_id=? ORDER BY rom_offset", proj["id"])
    regions = net.store.all("SELECT * FROM data_regions WHERE project_id=? ORDER BY rom_offset", proj["id"])
    blocks = _blocks(rows, regions, len(image))
    named = [f"{(r['rom_offset'] or 0) // BANK_SIZE:02x}:{r['vram'] or 0:04x} {r['name']}" for r in rows if LABEL.match(r["name"])]
    log("disassembling your copy with mgbdis, to see where its labels are")
    try:  # every function starts a .code block, so mgbdis decodes an instruction there for its name
        at_labels = labels(rom, sym="\n".join(blocks + named) + "\n")
    except RomError as e:
        raise NetworkError(f"mgbdis can't disassemble this game: {e}") from None
    sym, notes, matched, unplaced = list(blocks), [], 0, []
    for r in rows:
        bank, addr = (r["rom_offset"] or 0) // BANK_SIZE, r["vram"] or 0
        why = json.loads(r["meta"] or "{}").get("asm_code") or ""
        if not LABEL.match(r["name"]):
            continue
        if (bank, addr) not in at_labels:  # mgbdis is mid-instruction there: a name would have no label to go on
            unplaced.append(r["name"])
            continue
        sym.append(f"{bank:02x}:{addr:04x} {r['name']}")
        if why.startswith("padding"):
            sym.append(f"{bank:02x}:{addr:04x} .data:{r['size']:x}")  # shown as bytes, not as nops
        said = [f"Set aside: {why}"] if why else []
        if r["status"] == "matched" and r["matched_source"]:
            (out / "c").mkdir(exist_ok=True)
            (out / "c" / f"{r['name']}.c").write_text(
                f"/* {r['name']} (bank {bank}, ${addr:04x}): SDCC (GBDK-2020, flags {' '.join(cfg['compiler']['flags'])})"
                f" compiles this to exactly the original code, with context.h. */\n#include \"context.h\"\n\n"
                f"{r['matched_source'].strip()}\n", encoding="utf-8")
            said.append(f"Matched in C: c/{r['name']}.c")
            matched += 1
        for n in net.store.all("SELECT text FROM notes WHERE function_id=? ORDER BY id DESC LIMIT ?", r["id"], NOTES_PER_LABEL):
            text = " ".join(n["text"].split())
            said.append(text if len(text) <= NOTE_CHARS else text[:NOTE_CHARS - 3] + "...")
        notes += [f"{r['name']}: {line}" for text in said for line in textwrap.wrap(text, 110)]
    (out / "baserom.sym").write_text(
        "; for mgbdis: where each function starts (.code:length in hex, so it decodes from there), what isn't code\n"
        "; (.data:length: tables, padding, bytes the code never reaches), and names (bank:address Name)\n"
        + "\n".join(sym) + "\n", encoding="utf-8")
    (out / "comments.txt").write_text("\n".join(notes) + ("\n" if notes else ""), encoding="utf-8")
    if matched:
        (out / "c" / "context.h").write_text(net._context(proj["id"])["header"], encoding="utf-8")

    (out / "build.json").write_text(json.dumps({"title": proj["name"], "platform": cfg.get("platform"), "image": base,
                                                "sha1": hashlib.sha1(image).hexdigest()}, indent=1), encoding="utf-8")
    shutil.copyfile(Path(__file__).with_name("export_gb_build.py"), out / "build.py")
    shutil.copyfile(rom, out / base)
    (out / ".gitignore").write_text(f"build/\n{base}\n", encoding="utf-8")
    _docs(out, proj["name"], base, matched, len(rows))

    log("building the exported project to check it rebuilds the game byte for byte")
    proc = subprocess.run(capped([sys.executable, "build.py"]), cwd=out, capture_output=True, text=True, timeout=3600,
                          encoding="utf-8", errors="replace")
    identical = proc.returncode == 0 and "identical" in proc.stdout
    if not identical:
        log((proc.stdout + proc.stderr)[-3000:])
    if unplaced:
        log(f"{len(unplaced)} names left out: mgbdis decodes no instruction at their address ({', '.join(unplaced[:8])})")
    return {"path": str(out), "identical": identical, "matched": matched, "functions": len(rows),
            "fallback": [(n, "mgbdis decodes no instruction at its address: not named") for n in unplaced],
            "log": (proc.stdout + proc.stderr)[-3000:]}


def _blocks(rows, regions, size: int) -> list[str]:
    """mgbdis blocks for the project's split: a `.code` block at every function start (up to the next start or data
    region in its bank) and a `.data` block for every data region, so the disassembly has the split's layout."""
    placed = sorted((r for r in rows if r["rom_offset"] is not None), key=lambda r: r["rom_offset"])
    rows = [r for k, r in enumerate(placed) if not 0x104 <= r["rom_offset"] < 0x150
            and not (k and _mid_instruction(r, placed[k - 1]))]
    bounds = sorted({r["rom_offset"] for r in rows}
                    | {r["rom_offset"] for r in regions} | {r["rom_offset"] + r["size"] for r in regions})
    out = []
    for r in rows:
        flat = r["rom_offset"]
        k = bisect.bisect_right(bounds, flat)
        end = min(bounds[k] if k < len(bounds) else size, (flat // BANK_SIZE + 1) * BANK_SIZE)
        out.append(f"{flat // BANK_SIZE:02x}:{r['vram'] or 0:04x} .code:{end - flat:x}")
    for r in regions:
        flat, n = r["rom_offset"], r["size"]
        while n > 0:  # a block stays in its bank
            take = min(n, (flat // BANK_SIZE + 1) * BANK_SIZE - flat)
            cpu = flat if flat < BANK_SIZE else BANK_SIZE + flat % BANK_SIZE
            out.append(f"{flat // BANK_SIZE:02x}:{cpu:04x} .data:{take:x}")
            flat, n = flat + take, n - take
    return out


def _mid_instruction(r, prev) -> bool:
    """Whether a function starts inside an instruction of the one before it (an older split's guess): a block there
    would cut that instruction in two, so it gets none (and its name, no label)."""
    flat = r["rom_offset"]
    if prev["rom_offset"] + (prev["size"] or 0) <= flat:
        return False
    code = bytes(prev["target"] or b"")
    starts = {a for a, _t, _ln in sm83.disassemble(code, prev["rom_offset"])}
    return flat not in starts


def _docs(out: Path, title: str, base: str, matched: int, total: int) -> None:
    (out / "README.md").write_text(f"""# {title} (disassembly)

The game as assembly that rebuilds it byte for byte, with the names and notes worked out with
[decomp.wtf](https://decomp.wtf). Most Game Boy games were written in assembly: this is their source, the base for
mods, translations and ports. {matched} of the {total} functions found so far are also matched in C (in `c/`).

## Build

1. Your own copy of the game is here as `{base}` (it is in `.gitignore`; never commit it).
2. `python build.py`: it disassembles your copy with [mgbdis](https://github.com/mattcurrie/mgbdis) into
   `build/disassembly/` with the names in `baserom.sym` and the comments in `comments.txt`, builds it with
   [RGBDS](https://rgbds.gbdev.io), and checks the result against your copy. Needs decomp.wtf installed (it pins
   mgbdis and RGBDS), or RGBDS on `PATH` and `MGBDIS` set to the path of `mgbdis.py`.

## Layout

| Path | What it is |
| :-- | :-- |
| `baserom.sym` | Where every function starts (`.code:length`), what isn't code (`.data:length`: tables, padding, bytes the code never reaches) and every function's name (`bank:address Name`). mgbdis reads it; add labels and `.data`/`.text`/`.image` blocks here. |
| `comments.txt` | What's known about each routine (`Name: text`), put above it in the disassembly. |
| `c/` | Functions matched in C: SDCC (GBDK-2020) compiles each to exactly the original code. For reference: the build is the assembly. |
| `build.py`, `build.json` | The build, and which game it's for. |

`build/disassembly/` is made from your copy on every build, so keep your work in `baserom.sym` and `comments.txt`.
To change the game itself, copy `build/disassembly/` elsewhere and edit it there: its `Makefile` builds it with RGBDS
and lets rgbfix write the header's new checksums.

The game's code and data belong to their rights holder: keep this tree to yourself unless you have the right to
share it.
""", encoding="utf-8")
