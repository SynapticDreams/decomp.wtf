"""Catalog evidence for an SMS/GG cartridge board: a known dump's MAME software-list record, never a declaration.

MAME describes the board each dump needs (`slot`; empty: its default Sega-compatible device, which also runs small
mapperless ROMs). A match identifies the dump by SHA-1 of the normalized image; it does not establish the wiring of
the cartridge in hand, and a missing record proves nothing (see smsdb/README.md).
"""
from __future__ import annotations

import functools
import hashlib
import json
from pathlib import Path

DB = Path(__file__).with_name("smsdb") / "softlist.json"
# MAME slot boards the analysis models; every other board is recorded, not supported
MODELS = {"": "sega", "codemasters": "codemasters", "korean": "korean"}


@functools.cache
def _records() -> dict[str, list[tuple[str, str, tuple[str, ...]]]]:
    data = json.loads(DB.read_text(encoding="utf-8"))
    out: dict[str, list] = {}
    for sha1, listed, slot, flags in data["records"]:
        out.setdefault(sha1, []).append((listed, slot, tuple(flags)))
    return out


def source() -> dict:
    data = json.loads(DB.read_text(encoding="utf-8"))
    return {key: data[key] for key in ("source", "license", "extracted", "list_sha256")}


def lookup(image: bytes) -> dict:
    """{"available", "sha1", "matches": [{"list", "board", "models", "sms_mode", "battery"}], "source", "message"}."""
    try:
        records = _records()
        meta = source()
    except (OSError, ValueError, KeyError, TypeError):
        return {"available": False, "matches": [], "message": "The bundled software-list catalog is unavailable."}
    sha1 = hashlib.sha1(image).hexdigest()
    matches = []
    for listed, slot, flags in records.get(sha1, []):
        model = MODELS.get(slot, "unsupported")
        models = [model] + (["mapperless"] if model == "sega" and len(image) <= 0xC000 else [])
        matches.append({"list": listed, "board": slot or "default", "models": models,
                        "sms_mode": "sms_mode" in flags, "battery": "battery" in flags})
    return {"available": True, "sha1": sha1, "matches": matches, "source": meta,
            "message": ("A known dump: the catalog names the board MAME uses for it. It doesn't establish the wiring "
                        "of this cartridge; declare the model from evidence you have reviewed." if matches else
                        "No catalog record for this exact image; that says nothing about its board.")}
