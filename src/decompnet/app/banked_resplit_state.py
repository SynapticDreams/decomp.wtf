"""Bounded private snapshots of project work; deterministic digests guard concurrent edits."""
from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
import zlib

from ..network import NetworkError

VERSION = 1
MAX_BYTES = 64 * 1024 * 1024
MAX_ROWS = 100_000
TABLES = {
    "functions": ("project_id=?", "id"),
    "attempts": ("function_id IN (SELECT id FROM functions WHERE project_id=?)", "id"),
    "claims": ("function_id IN (SELECT id FROM functions WHERE project_id=?)", "function_id"),
    "notes": ("project_id=?", "id"),
    "symbols": ("project_id=?", "name"),
    "data_regions": ("project_id=?", "rom_offset"),
    "corrections": ("project_id=?", "id"),
    "context_versions": ("project_id=?", "unit,version"),
    "twin_misses": ("project_id=? OR function_id IN (SELECT id FROM functions WHERE project_id=?)", "function_id,source_hash"),
}


def external(root: Path, rom_file: str) -> dict:
    out = {}
    for suffix in (".sym", ".cdl", ".trace"):
        path = (root / rom_file).with_suffix(suffix)
        try:
            digest, count = hashlib.sha256(), 0
            with path.open("rb") as stream:
                while chunk := stream.read(65536):
                    count += len(chunk)
                    if count > MAX_BYTES:
                        raise NetworkError("resplit sidecar exceeds the 64 MiB verification budget")
                    digest.update(chunk)
            out[suffix] = digest.hexdigest()
        except FileNotFoundError:
            out[suffix] = None
        except OSError:
            raise NetworkError("resplit symbol/coverage input is unavailable") from None
    return out


def _bytes(db, table, where, args):
    columns = [row["name"] for row in db.execute(f"PRAGMA table_info({table})")]
    size = "+".join(f'COALESCE(length(CAST("{column}" AS BLOB)),0)' for column in columns)
    return db.execute(f"SELECT COALESCE(SUM({size}),0) FROM {table} WHERE {where}", args).fetchone()[0]


def capture(db, pid: int, inputs: dict) -> dict:
    size = _bytes(db, "projects", "id=?", (pid,))
    if size > MAX_BYTES:
        raise NetworkError("resplit snapshot exceeds the 64 MiB work budget")
    project = db.execute("SELECT * FROM projects WHERE id=?", (pid,)).fetchone()
    if project is None:
        raise NetworkError("the project was removed during resplit")
    tables, count = {}, 1
    for table, (where, order) in TABLES.items():
        args = (pid,) * where.count("?")
        count += db.execute(f"SELECT COUNT(*) FROM {table} WHERE {where}", args).fetchone()[0]
        if count > MAX_ROWS:
            raise NetworkError("resplit snapshot exceeds the 100,000-row budget")
        size += _bytes(db, table, where, args)
        if size > MAX_BYTES:
            raise NetworkError("resplit snapshot exceeds the 64 MiB work budget")
        rows = db.execute(f"SELECT * FROM {table} WHERE {where} ORDER BY {order} LIMIT ?",
                          (*args, MAX_ROWS)).fetchall()
        tables[table] = [dict(row) for row in rows]
    return {"version": VERSION, "project": dict(project), "tables": tables, "inputs": inputs}


def _blob(value):
    if isinstance(value, bytes):
        return {"$blob": base64.b64encode(value).decode("ascii")}
    raise TypeError("unsupported resplit snapshot value")


def encode(state: dict) -> tuple[bytes, str]:
    compressor, digest = zlib.compressobj(), hashlib.sha256()
    compressed, count = bytearray(), 0
    for part in json.JSONEncoder(default=_blob, sort_keys=True, separators=(",", ":")).iterencode(state):
        raw = part.encode("utf-8")
        count += len(raw)
        if count > MAX_BYTES:
            raise NetworkError("resplit snapshot exceeds the 64 MiB work budget")
        digest.update(raw)
        compressed.extend(compressor.compress(raw))
    compressed.extend(compressor.flush())
    return bytes(compressed), digest.hexdigest()


def decode(payload: bytes, digest: str) -> dict:
    def blob(value):
        return base64.b64decode(value["$blob"], validate=True) if set(value) == {"$blob"} else value

    try:
        decompressor = zlib.decompressobj()
        raw = decompressor.decompress(payload, MAX_BYTES + 1)
        if len(raw) > MAX_BYTES or not decompressor.eof or decompressor.unused_data or decompressor.unconsumed_tail:
            raise ValueError("invalid snapshot compression")
        if hashlib.sha256(raw).hexdigest() != digest:
            raise ValueError("snapshot digest differs")
        state = json.loads(raw, object_hook=blob)
        if type(state["version"]) is not int or state["version"] != VERSION or set(state["tables"]) != set(TABLES):
            raise ValueError("unsupported snapshot version/tables")
        return state
    except (ValueError, TypeError, KeyError, zlib.error):
        raise NetworkError("resplit snapshot is invalid or exceeds its decode budget") from None
