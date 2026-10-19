"""Restore a verified project snapshot without replacing another project's reused IDs."""
from __future__ import annotations

from ..network import NetworkError
from ..store_annotations import restore_row
from .banked_resplit_state import MAX_ROWS, TABLES


def restore(db, pid: int, state: dict) -> None:
    if not isinstance(state.get("project"), dict) or state["project"].get("id") != pid:
        raise NetworkError("resplit snapshot belongs to another project")
    count, prepared = 1, {}
    for table in TABLES:
        rows = state["tables"][table]
        columns = {r["name"] for r in db.execute(f"PRAGMA table_info({table})")}
        if isinstance(rows, list):
            rows = [restore_row(table, row, columns) for row in rows]
        if not isinstance(rows, list) or any(not isinstance(row, dict) or set(row) != columns for row in rows):
            raise NetworkError("resplit snapshot schema differs from the current database")
        prepared[table] = rows
        count += len(rows)
        if count > MAX_ROWS:
            raise NetworkError("resplit snapshot exceeds its row budget")
        if table in ("functions", "notes", "corrections", "attempts"):
            own, _order = TABLES[table]
            for start in range(0, len(rows), 500):
                ids = [row["id"] for row in rows[start:start + 500]]
                args = (pid,) * own.count("?")
                if db.execute(f"SELECT 1 FROM {table} WHERE id IN ({','.join('?' * len(ids))}) "
                              f"AND COALESCE(({own}),0)=0 LIMIT 1", (*ids, *args)).fetchone():
                    raise NetworkError("saved resplit IDs are now used outside this project; history is retained")
    ids = [row["id"] for row in state["tables"]["functions"]]
    for table in ("attempts", "claims", "notes", "twin_misses"):
        own, _order = TABLES[table]
        for start in range(0, len(ids), 500):
            chunk = ids[start:start + 500]
            args = (pid,) * own.count("?")
            if db.execute(f"SELECT 1 FROM {table} WHERE function_id IN ({','.join('?' * len(chunk))}) "
                          f"AND COALESCE(({own}),0)=0 LIMIT 1", (*chunk, *args)).fetchone():
                raise NetworkError("saved function IDs have new references outside this project; history is retained")
    # Related rows must be removed while their current function IDs still establish ownership.
    for table, (where, _order) in TABLES.items():
        if table != "functions":
            db.execute(f"DELETE FROM {table} WHERE {where}", (pid,) * where.count("?"))
    db.execute("DELETE FROM functions WHERE project_id=?", (pid,))
    for table in TABLES:
        for row in prepared[table]:
            columns = list(row)
            db.execute(f"INSERT INTO {table} ({','.join(columns)}) VALUES ({','.join('?' * len(columns))})",
                       tuple(row[column] for column in columns))
    db.execute("UPDATE projects SET config=? WHERE id=?", (state["project"]["config"], pid))
