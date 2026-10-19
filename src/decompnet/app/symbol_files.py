"""Legacy GB symbol files and common paths, separate from engine orchestration."""
import re
import time
from pathlib import Path

from ..network import NetworkError
from ..rom.symbols import AUTO_NAME


LINE = re.compile(r"^([0-9A-Fa-f]{1,4}):([0-9A-Fa-f]{4})\s+([A-Za-z_][A-Za-z0-9_@#$]*(?:\.[A-Za-z0-9_@#$]+)?|"
                       r"\.(?:code|data|text|byt|asc|padding):[0-9A-Fa-f]{1,5}(?::[0-9A-Za-z,]{1,40})?)\s*$")

def path(net, proj) -> Path:
    cfg = net.cfg(proj)
    return (Path(proj["root"]) / cfg["rom"]["file"]).with_suffix(".sym")

def present_legacy(net, slug: str) -> dict | None:
    path = net._sym_path(net._project(slug))
    if not path.is_file():
        return None
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    cfg = net.cfg(net._project(slug))
    return {"names": sum(1 for x in lines if x.strip() and not x.split()[-1].startswith(".") and not x.startswith(";")),
            "blocks": sum(1 for x in lines if x.strip() and x.split()[-1].startswith(".")),
            "from": cfg.get("symbol_file", {}).get("from", path.name)}

def import_legacy(net, slug: str, text: str, name: str = "") -> dict:
    """A symbol file the user chose (RGBDS / mgbdis / WLA-DX `bank:address Name` lines, with `.data:length` style
    blocks on the Game Boy), for this project only: kept next to its copy of the game, so splitting again uses its
    names and blocks, and functions with automatic names at its labels are named after them (not after the
    file's own automatic ones, `_LABEL_9D9_`: those only say where code starts). Only well-formed lines are kept
    (comments, headers and anything else, a refusal test string included, never reach an agent); nothing is
    shared."""
    from .engine import _GENERATED

    proj = net._project(slug)
    if (net.cfg(proj).get("arch") or "").lower() not in ("sm83", "z80") or net.fork_slug(slug):
        raise NetworkError("importing a symbol file is for Game Boy and Master System projects for now")
    if slug in net.links:
        raise NetworkError("a room member's copy follows its host: the host imports it")
    if len(text or "") > 8 << 20:
        raise NetworkError("that file is over 8 MB: a symbol file is much smaller")
    kept, dropped = [], 0
    for line in str(text or "").splitlines():
        line = line.split(";", 1)[0].strip()
        if not line:
            continue
        if (m := LINE.match(line)) and len(m.group(3)) <= 64:
            kept.append(f"{int(m.group(1), 16):02x}:{m.group(2).lower()} {m.group(3)}")
        else:
            dropped += 1
    if not kept:
        raise NetworkError("no `bank:address Name` lines in that file: is it an RGBDS, BGB, mgbdis or WLA-DX symbol "
                           "file?")
    path = net._sym_path(proj)
    path.write_text("; imported into decomp.wtf for this project only\n" + "\n".join(kept) + "\n", encoding="utf-8")
    net._update_cfg(slug, lambda cfg: cfg.update(symbol_file={"from": Path(name).name or path.name,
                                                                 "at": time.time()}))
    renamed = 0
    you, _ = net.local_agent("you")
    names = {}
    for line in kept:
        loc, label = line.split()
        if not label.startswith((".", "_LABEL_", "_DATA_", "_RAM_")) and "." not in label:
            bank, cpu = (int(x, 16) for x in loc.split(":"))
            names[(bank, cpu)] = label
    taken = {r["name"] for r in net.store.all("SELECT name FROM functions WHERE project_id=?", proj["id"])}
    for r in net.store.all("SELECT name, rom_offset, vram FROM functions WHERE project_id=?", proj["id"]):
        label = names.get(((r["rom_offset"] or 0) // 0x4000, r["vram"] or 0))
        if label and label not in taken and (AUTO_NAME.match(r["name"]) or _GENERATED.search(r["name"])):
            try:
                if net.rename_symbol(you, slug, r["name"], label, "from the imported symbol file").startswith("✅"):
                    taken.add(label)
                    renamed += 1
            except NetworkError:
                pass
    with net.store.tx() as db:
        net._event(db, proj["id"], you.id, "import", f"symbol file: {len(kept)} lines kept, {dropped} left out")
    return {"kept": len(kept), "dropped": dropped, "renamed": renamed, "symbol_file": net.symbol_file(slug)}

def remove_legacy(net, slug: str) -> dict:
    path = net._sym_path(net._project(slug))
    path.unlink(missing_ok=True)
    net._update_cfg(slug, lambda cfg: cfg.pop("symbol_file", None))
    return net.corrections(slug)
