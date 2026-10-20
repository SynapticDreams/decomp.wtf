"""SDCC library recognition for SMS/GG projects (rom/sdcc_libs.py): scan, then optionally name and set aside.

Signatures come from the pinned GBDK-2020's installed Z80 libraries (z80.lib, and sms.lib or gg.lib) and from
library files a person adds (kept in the workspace's local cache, as PS1 signatures are). Applying names only
functions whose whole recorded body a unique hit covers, keeps any name a person or agent gave, and skips claimed,
accepted and explicitly reopened work.
"""
from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
import re
import tempfile

from ..network import NetworkError
from ..rom import sdcc_libs, sms_identity

MAX_FILES, MAX_UPLOAD, MAX_CACHE = 16, 32 << 20, 128 << 20
DEFAULT_NAME = re.compile(r"^func_[0-9A-Fa-f]{3}_[0-9A-Fa-f]{4}$")
SETTLED = ("matched", "documented")


def gbdk_libraries(platform: str) -> list[tuple[str, bytes]]:
    from .. import toolchains

    if not toolchains.installed("gbdk-2020"):
        return []
    base = toolchains.path("gbdk-2020") / "gbdk" / "lib"
    names = ["z80/z80.lib", f"{'gg' if platform == 'gg' else 'sms'}/{'gg' if platform == 'gg' else 'sms'}.lib"]
    return [(f"GBDK-2020 {name}", (base / name).read_bytes()) for name in names if (base / name).is_file()]


def _cache(net) -> Path:
    return net.workspace / ".decomp" / "sdcc-libraries"


def _store(net, files) -> None:
    """Validate every uploaded library before keeping any of them."""
    if not isinstance(files, list) or len(files) > MAX_FILES:
        raise NetworkError(f"provide at most {MAX_FILES} library files at a time")
    prepared, total = [], 0
    for item in files:
        if not isinstance(item, dict) or not isinstance(item.get("data"), str) or not isinstance(item.get("name"), str):
            raise NetworkError("each library needs a name and base64 data")
        try:
            data = base64.b64decode(item["data"], validate=True)
        except ValueError as exc:
            raise NetworkError("invalid base64 library upload") from exc
        total += len(data)
        if total > MAX_UPLOAD:
            raise NetworkError("library upload exceeds 32 MiB")
        name = Path(item["name"]).name[:120] or "library"
        try:
            functions, _skipped = sdcc_libs.from_library(name, data)
        except ValueError as exc:
            raise NetworkError(f"{name}: {exc}") from None
        if not functions:
            raise NetworkError(f"{name}: no SDCC code areas with symbols in it")
        prepared.append((hashlib.sha256(data).hexdigest(), name, data))
    cache = _cache(net)
    cache.mkdir(parents=True, exist_ok=True)
    for digest, name, data in prepared:
        with tempfile.NamedTemporaryFile(dir=cache, delete=False) as tmp:
            tmp.write(json.dumps({"name": name}).encode() + b"\n" + data)
            staging = Path(tmp.name)
        staging.replace(cache / f"{digest}.lib")


def _cached(net) -> list[tuple[str, bytes]]:
    out, total = [], 0
    for path in sorted(_cache(net).glob("*.lib")):
        total += path.stat().st_size
        if total > MAX_CACHE:
            raise NetworkError("local SDCC library cache exceeds 128 MiB")
        header, _, data = path.read_bytes().partition(b"\n")
        out.append((str(json.loads(header).get("name", path.stem)), data))
    return out


def identify(net, slug: str, files=None, apply: bool = False, log=print) -> dict:
    proj = net._project(slug)
    cfg = net.cfg(proj)
    if net.fork_slug(slug) or cfg.get("platform") not in ("sms", "gg") or cfg.get("kind") != "rom":
        raise NetworkError("SDCC library recognition is for Master System and Game Gear ROM projects")
    if net._link(slug) is not None:
        raise NetworkError("identify libraries on the room's host copy")
    if files:
        _store(net, files)
    libraries = gbdk_libraries(cfg["platform"]) + _cached(net)
    functions, unreadable = [], []
    for name, data in libraries:
        found, skipped = sdcc_libs.from_library(name, data)
        functions += found
        unreadable += [f"{name}: {why}" for why in skipped]
    try:
        image = sms_identity.strip_copier_header((Path(proj["root"]) / cfg["rom"]["file"]).read_bytes())
        sms_identity.verify_normalized(image, cfg["rom"].get("identity"), cfg["rom"].get("sha1"))
    except (OSError, ValueError) as exc:
        raise NetworkError(f"the original input is missing or differs: {exc}") from None
    report = sdcc_libs.scan(image, functions)
    report.update({"libraries": [name for name, _ in libraries], "unreadable": unreadable[:20], "applied": 0,
                   "renamed": 0, "label_count": len(report["hits"]), "conflict_count": len(report["conflicts"])})
    if apply and not report["truncated"]:
        _apply(net, slug, proj, report)
    summary = {k: v for k, v in report.items() if k not in ("hits", "conflicts")}
    summary["hits"], summary["conflicts"] = report["hits"][:100], report["conflicts"][:100]
    net._update_cfg(slug, lambda current: current.__setitem__("sdcc_libraries", summary))
    log(f"SDCC libraries: {report['patterns']} usable patterns from {len(libraries)} libraries, "
        f"{len(report['hits'])} labels, {report['applied']} functions recognized")
    return report


def _apply(net, slug, proj, report) -> None:
    agent, _ = net.local_agent("you")
    rows = {row["rom_offset"]: row for row in net.store.all("SELECT * FROM functions WHERE project_id=?", proj["id"])}
    for hit in report["hits"]:
        fn = rows.get(hit["rom_offset"])
        if fn is None or fn["rom_offset"] + fn["size"] > hit["matched_end"] or fn["status"] in SETTLED:
            continue
        if net.store.one("SELECT 1 FROM claims WHERE function_id=?", fn["id"]):
            continue
        meta = json.loads(fn["meta"] or "{}")
        if meta.get("for_agents"):
            continue  # (a person returned it to agents)
        if DEFAULT_NAME.fullmatch(fn["name"]) and not net.store.one(
                "SELECT 1 FROM functions WHERE project_id=? AND name=? AND id<>?", proj["id"], hit["name"], fn["id"]):
            try:
                report["renamed"] += net.rename_symbol(agent, slug, fn["name"], hit["name"],
                                                       "SDCC library signature").startswith("✅")
            except NetworkError:
                pass  # recognition still holds when the name can't change
        meta.update({"kind": "library", "library": hit,
                     "asm_code": f"recognized SDCC library function {hit['name']} ({', '.join(hit['libraries'])})"})
        with net.store.tx() as db:
            report["applied"] += db.execute(
                "UPDATE functions SET meta=?, status=CASE WHEN status='open' THEN 'asm' ELSE status END "
                "WHERE id=? AND id NOT IN (SELECT function_id FROM claims)", (json.dumps(meta), fn["id"])).rowcount
