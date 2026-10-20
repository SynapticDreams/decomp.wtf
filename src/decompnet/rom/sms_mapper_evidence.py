"""Bounded byte-pattern suggestions, never mapper selection or executed-instruction evidence.

The report also carries the software-list catalog's record for a known dump (rom/sms_mapper_db.py), kept apart
from the byte-pattern candidates: both are suggestions, and neither changes the declaration.
"""
from __future__ import annotations

from . import sms_mapper_db

SCAN_BYTES = 0x10000
RECORDS = 32
SELECTORS = {0xFFFC: "sega", 0xFFFD: "sega", 0xFFFE: "sega", 0xFFFF: "sega",
             0x0000: "codemasters", 0x4000: "codemasters", 0x8000: "codemasters", 0xA000: "korean"}


def inspect(image: bytes) -> dict:
    scanned = min(len(image), SCAN_BYTES)
    records, hits = [], set()
    total = 0
    for offset in range(max(0, scanned - 2)):
        if image[offset] != 0x32:  # possible LD (nn),A; data/operands can contain the same bytes
            continue
        address = int.from_bytes(image[offset + 1:offset + 3], "little")
        if (mapper := SELECTORS.get(address)) is not None:
            total += 1
            hits.add(mapper)
            if len(records) < RECORDS:
                records.append({"offset": offset, "address": address, "mapper": mapper, "kind": "byte-pattern"})
    candidates = [{"mapper": mapper, "confidence": "low"} for mapper in sorted(hits)]
    if len(image) <= 0xC000:
        candidates.append({"mapper": "mapperless", "confidence": "low", "reason": "size fits the flat address space"})
    return {"available": True, "confidence": "low", "ambiguous": True, "requires_declaration": True,
            "scan_bytes": scanned, "total_bytes": len(image), "scan_truncated": scanned < len(image),
            "record_limit": RECORDS, "pattern_count": total, "records_truncated": total > len(records),
            "candidates": candidates, "evidence": records, "catalog": sms_mapper_db.lookup(image),
            "message": "Byte patterns can be data or patched code; size and missing patterns prove no mapper. "
                       "Review independent wiring evidence before declaring a model."}
