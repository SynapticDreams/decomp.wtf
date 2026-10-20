"""Real SMS programs with published source, built from a pinned commit as end-to-end fixtures for the SMS gate.

Nothing of them is kept in this repository: each is fetched with git at an exact commit (the commit hash pins its
content), assembled with the pinned WLA-DX, and its symbol file gives the ground truth the split is checked against.

- zexall-sms (maxim-zhao/zexall-sms, GPL-2.0): the ZEXALL Z80 instruction exerciser, ported to the Master System.
  Its two fonts are 1-bit PNGs its makefile converts with BMP2Tile; `one_bpp` does the same conversion (8x8 tiles,
  left to right then top to bottom, a set bit for a nonzero palette index). Font bytes are data: their exact values
  don't change the program's structure.
"""
from __future__ import annotations

import os
from pathlib import Path
import re
import struct
import subprocess
import zlib

FIXTURES = {
    "zexall-sms": {"git": "https://github.com/maxim-zhao/zexall-sms", "commit": "8bfcd2ca594fa95c8dd7be33da64043b706e5480"},
}


def fetch(name: str, cache: Path) -> Path:
    """The fixture's source tree at its pinned commit, cloned once into `cache`."""
    spec = FIXTURES[name]
    folder = cache / f"{name}-{spec['commit'][:12]}"
    if not (folder / ".git").is_dir() or _head(folder) != spec["commit"]:
        folder.mkdir(parents=True, exist_ok=True)
        git = ["git", "-c", "advice.detachedHead=false", "-C", str(folder)]
        subprocess.run([*git, "init", "-q"], check=True)
        subprocess.run([*git, "fetch", "-q", "--depth", "1", spec["git"], spec["commit"]], check=True)
        subprocess.run([*git, "checkout", "-q", "--force", "FETCH_HEAD"], check=True)
    if _head(folder) != spec["commit"]:
        raise RuntimeError(f"{name}: the checkout isn't the pinned commit")
    return folder


def _head(folder: Path) -> str:
    run = subprocess.run(["git", "-C", str(folder), "rev-parse", "HEAD"], capture_output=True, text=True)
    return run.stdout.strip() if run.returncode == 0 else ""


def one_bpp(png: bytes) -> bytes:
    """A non-interlaced 1-bit indexed PNG as 1bpp 8x8 tiles (8 bytes each, a row per byte, leftmost pixel high)."""
    if png[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("not a PNG")
    at, idat, header = 8, b"", None
    while at < len(png):
        size, kind = struct.unpack(">I4s", png[at:at + 8])
        body = png[at + 8:at + 8 + size]
        if kind == b"IHDR":
            header = struct.unpack(">IIBBBBB", body)
        elif kind == b"IDAT":
            idat += body
        at += 12 + size
    if header is None or header[2:4] != (1, 3) or header[6] != 0:
        raise ValueError("expected a non-interlaced 1-bit indexed PNG")
    width, height = header[:2]
    if width % 8 or height % 8:
        raise ValueError("expected whole 8x8 tiles")
    stride, raw, rows, previous = width // 8, zlib.decompress(idat), [], bytes(width // 8)
    for y in range(height):
        kind, line = raw[y * (stride + 1)], bytearray(raw[y * (stride + 1) + 1:(y + 1) * (stride + 1)])
        for x in range(stride):  # (1-bit pixels: the filters' "previous byte" is the byte before)
            left, up, corner = line[x - 1] if x else 0, previous[x], previous[x - 1] if x else 0
            if kind == 1:
                line[x] = (line[x] + left) & 255
            elif kind == 2:
                line[x] = (line[x] + up) & 255
            elif kind == 3:
                line[x] = (line[x] + (left + up) // 2) & 255
            elif kind == 4:
                p = left + up - corner
                pa, pb, pc = abs(p - left), abs(p - up), abs(p - corner)
                line[x] = (line[x] + (left if pa <= pb and pa <= pc else up if pb <= pc else corner)) & 255
            elif kind:
                raise ValueError("unknown PNG filter")
        rows.append(bytes(line))
        previous = bytes(line)
    return b"".join(rows[ty * 8 + y][tx:tx + 1] for ty in range(height // 8) for tx in range(stride) for y in range(8))


def build_zexall(source: Path, out: Path, wla: tuple[Path, Path]) -> tuple[bytes, str]:
    """(zexall.sms, its WLA symbol file), assembled as its makefile does (with the undocumented flags tested)."""
    work = out / "zexall"
    work.mkdir(parents=True, exist_ok=True)
    for path in (source / "source").iterdir():
        if path.is_file() and path.suffix in (".asm", ".inc", ".png") or path.name == "linkfile":
            (work / path.name).write_bytes(path.read_bytes())
    for png in ("ZX_Eurostile", "Envious"):
        (work / f"{png}.1bpp").write_bytes(one_bpp((work / f"{png}.png").read_bytes()))
    asm, link = wla
    env = {**os.environ, "LC_ALL": "C"}
    subprocess.run([str(asm), "-D", "UndocumentedFlags", "-o", "zexall.sms.o", "zexall.sms.asm"], cwd=work, check=True,
                   capture_output=True, env=env)
    subprocess.run([str(link), "-d", "-r", "-S", "linkfile", "zexall.sms"], cwd=work, check=True, capture_output=True,
                   env=env)
    return (work / "zexall.sms").read_bytes(), (work / "zexall.sym").read_text(encoding="utf-8")


def called_labels(source: str) -> set[str]:
    """Labels the source calls (`call [cc,] Label`, after a label or WLA's `-:`/`+:` ones): each starts a routine."""
    return {m for m in re.findall(r"^\s*(?:[\w+-]+:)?\s*call\s+(?:(?:nz|z|nc|c|po|pe|p|m)\s*,\s*)?([A-Za-z_]\w*)\s*(?:;|$)",
                                  source, re.M | re.I)}
