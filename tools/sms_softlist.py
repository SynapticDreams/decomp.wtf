"""Extract cartridge-board evidence from MAME's SMS/GG software lists into src/decompnet/rom/smsdb/softlist.json.

    python tools/sms_softlist.py path/to/mame/hash/sms.xml path/to/mame/hash/gamegear.xml

The lists are CC0-1.0 (each file says so). Only what identifies a dump and describes its board is kept: the SHA-1
of a single-ROM cartridge or card, its `slot` board, MAME's `pin_42` Master System mode and `battery` features.
Titles, descriptions, publishers and part names are left out.
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "src" / "decompnet" / "rom" / "smsdb" / "softlist.json"
LISTS = {"sms.xml": "sms", "gamegear.xml": "gamegear"}


def records(path: Path, name: str) -> list[list]:
    text = path.read_text(encoding="utf-8")
    if not re.search(r"license:CC0-1\.0", text[:2048]):
        raise SystemExit(f"{path}: expected MAME's CC0-1.0 notice at the top of the list")
    out = []
    for software in ET.fromstring(text).iter("software"):
        for part in software.findall("part"):
            roms = [rom for area in part.findall("dataarea") if area.get("name") == "rom"
                    for rom in area.findall("rom") if rom.get("sha1")]
            if len(roms) != 1 or not re.fullmatch(r"[0-9a-f]{40}", roms[0].get("sha1", "")):
                continue  # (split dumps have no single-image hash to compare)
            features = {f.get("name"): f.get("value") for f in part.findall("feature")}
            flags = [flag for flag, on in (("sms_mode", features.get("pin_42") == "sms_mode"),
                                            ("battery", features.get("battery") == "yes")) if on]
            out.append([roms[0].get("sha1"), name, features.get("slot") or "", flags])
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("lists", nargs="+", type=Path, help="MAME hash/sms.xml and hash/gamegear.xml")
    args = parser.parse_args()
    rows, sources = [], {}
    for path in args.lists:
        if path.name not in LISTS:
            raise SystemExit(f"{path}: expected one of {', '.join(LISTS)}")
        sources[LISTS[path.name]] = hashlib.sha256(path.read_bytes()).hexdigest()
        rows += records(path, LISTS[path.name])
    rows = sorted({tuple(r[:3]) + (tuple(r[3]),): r for r in rows}.values())
    OUT.write_text(json.dumps({
        "format": 1, "source": "MAME software lists (https://github.com/mamedev/mame/tree/master/hash)",
        "license": "CC0-1.0", "extracted": datetime.date.today().isoformat(), "list_sha256": sources,
        "records": rows}, separators=(",", ":")) + "\n", encoding="utf-8")
    print(f"{len(rows)} records -> {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
