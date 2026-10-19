"""Monotonic function IDs keep deleted work from becoming another routine's history.

Rebuild follows https://www.sqlite.org/lang_altertable.html#making_other_kinds_of_table_schema_changes
and allocator semantics follow https://www.sqlite.org/autoinc.html. Explicit ID restoration remains possible.
"""
from __future__ import annotations

import re
import uuid

REFERENCES = (("functions", "id"), ("attempts", "function_id"), ("claims", "function_id"),
              ("notes", "function_id"), ("twin_misses", "function_id"))


def _floor(conn) -> int:
    values = [conn.execute(f"SELECT COALESCE(MAX({column}),0) FROM {table}").fetchone()[0] for table, column in REFERENCES]
    if any(type(value) is not int for value in values):
        raise ValueError("function references exceed the integer ID range")
    return max(0, *values)


def upgrade(conn) -> None:
    sql = conn.execute("SELECT sql FROM sqlite_schema WHERE name='functions' AND type='table'").fetchone()[0]
    rebuild = not re.search(r'\(\s*(?:"id"|id)\s+INTEGER\s+PRIMARY\s+KEY\s+AUTOINCREMENT\b', sql, re.I)
    sequence = conn.execute("SELECT 1 FROM sqlite_schema WHERE name='sqlite_sequence'").fetchone()
    current = conn.execute("SELECT seq FROM sqlite_sequence WHERE name='functions'").fetchone() if sequence else None
    allocated = current[0] if current and current[0] is not None else 0
    if type(allocated) is not int or not 0 <= allocated < 2**63:
        raise ValueError("invalid function ID allocation history")
    floor = max(_floor(conn), allocated)
    if not rebuild and allocated >= floor:
        return
    foreign_keys = conn.execute("PRAGMA foreign_keys").fetchone()[0]
    if conn.in_transaction:
        raise ValueError("function ID migration requires an idle connection")
    conn.execute("PRAGMA foreign_keys=OFF")
    try:
        conn.execute("BEGIN IMMEDIATE")
        floor = max(floor, _floor(conn))
        if rebuild:
            _rebuild(conn, sql)
        if not conn.execute("UPDATE sqlite_sequence SET seq=MAX(COALESCE(seq,0),?) WHERE name='functions'", (floor,)).rowcount:
            conn.execute("INSERT INTO sqlite_sequence(name,seq) VALUES('functions',?)", (floor,))
        if foreign_keys and any(row[2] == "functions" for row in conn.execute("PRAGMA foreign_key_check")):
            raise ValueError("function ID migration found invalid foreign references")
        conn.execute("COMMIT")
    except BaseException:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise
    finally:
        conn.execute(f"PRAGMA foreign_keys={int(foreign_keys)}")


def _rebuild(conn, sql: str) -> None:
    temporary = "functions_ids_" + uuid.uuid4().hex
    revised, count = re.subn(r"\bid\s+INTEGER\s+PRIMARY\s+KEY\b", "id INTEGER PRIMARY KEY AUTOINCREMENT", sql, count=1, flags=re.I)
    revised, named = re.subn(r'^CREATE\s+TABLE\s+(?:"functions"|functions)', f'CREATE TABLE "{temporary}"',
                            revised, count=1, flags=re.I)
    if count != 1 or named != 1:
        raise ValueError("unsupported function table format for ID migration")
    # Views/triggers can reference functions from another object; temporarily remove all of them
    # so schema validation never sees a reference to the table during its replacement.
    objects = conn.execute("SELECT type,name,sql FROM sqlite_schema WHERE type IN ('view','trigger') "
                           "OR (type='index' AND tbl_name='functions' AND sql IS NOT NULL)").fetchall()
    for kind, name, _sql in objects:
        if kind in ("view", "trigger"):
            quoted = name.replace('"', '""')
            conn.execute(f'DROP {kind.upper()} "{quoted}"')
    columns = ",".join('"' + row[1].replace('"', '""') + '"' for row in conn.execute("PRAGMA table_info(functions)"))
    conn.execute(revised)
    conn.execute(f'INSERT INTO "{temporary}" ({columns}) SELECT {columns} FROM functions')
    conn.execute("DROP TABLE functions")
    conn.execute(f'ALTER TABLE "{temporary}" RENAME TO functions')
    for kind in ("index", "view", "trigger"):
        for object_kind, _name, statement in objects:
            if object_kind == kind:
                conn.execute(statement)
