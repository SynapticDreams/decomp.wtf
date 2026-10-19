"""ROM symbol renaming and source regression checks, separate from metadata editing."""
import re
import time

from ..network import NetworkError
from ..rom.symbols import IDENT, Symbol, SymbolTable
from . import symbol_records
from .sms_annotation_context import guard


def rename(net, agent, proj, old, new, message=''):
    project = proj['slug']
    if net.cfg(proj).get("mapping"):
        raise NetworkError("mapping v1 keeps profile symbol names stable; aliases will be supported in a later version")
    link = net._link(project)
    if link is not None:
        text = link.call("/collab/rename", agent, old=old, new=new, message=message)
        if text.startswith("✅"):
            link.sync()
        return text
    work = guard(net, proj) if net.cfg(proj).get('platform') in ('sms', 'gg') else None
    old, new = old.strip(), new.strip()
    if not (IDENT.match(old) and IDENT.match(new)):
        raise NetworkError("old and new must be C identifiers")
    syms = net.symbols(proj["id"])
    if old not in syms.by_name and (m := re.fullmatch(r"func_(\d{3})_([0-9a-fA-F]{4})", old)):
        # an automatic name from an older listing (the function has a name now): banks share CPU addresses,
        # so its bank finds it, and what it's called now is what's renamed
        row = net.store.one("SELECT name FROM functions WHERE project_id=? AND vram=? AND unit=?", proj["id"],
                             int(m.group(2), 16), f"bank{int(m.group(1)):03d}")
        if row is not None and row["name"] != old:
            if row["name"] == new:
                return f"✅ {old} is already called {new}"
            old = row["name"]
    addr = syms.resolve(old)
    if addr is None:
        raise NetworkError(f"`{old}` is not a symbol of this ROM: use a name from the assembly (func_/D_...) "
                           f"or one given earlier")
    taken = syms.resolve(new)
    if taken is not None and taken != addr:
        raise NetworkError(f"`{new}` already names 0x{taken:08X}")
    word = re.compile(rf"\b{re.escape(old)}\b")
    trial = SymbolTable([Symbol(s.name, s.address, s.size, s.kind) for s in syms.by_name.values()])
    if old in trial.by_name:
        trial.rename(old, new)
    else:
        fnrow = net.store.one("SELECT size FROM functions WHERE project_id=? AND vram=?", proj["id"], addr)
        current, _ = syms.name_at(addr)
        base = syms.by_name.get(current) if current != f"D_{addr:08X}" else None
        trial.add(Symbol(new, addr, fnrow["size"] if fnrow else (base.size if base and base.address == addr else 0),
                         "func" if fnrow else (base.kind if base else "data")))
    units = net._unit_contexts(proj["id"])
    current_ctx = {u: net._context(proj["id"], u) for u in ({""} | units)}
    changed = {u: word.sub(new, c["header"]) for u, c in current_ctx.items() if word.search(c["header"])}
    matched = net.store.all("SELECT * FROM functions WHERE project_id=? AND status='matched'", proj["id"])
    rewritten = {r["id"]: word.sub(new, r["matched_source"]) for r in matched}
    renamed_rows = [dict(r) | {"name": new if r["name"] == old else r["name"]} for r in matched]
    header_for = lambda fn: changed.get(net._effective_unit(fn, units),
                                        current_ctx[net._effective_unit(fn, units)]["header"])
    net._sym_override[proj["id"]] = trial
    try:
        broken = net.regression_test(proj, None, sources=rewritten, only=renamed_rows, header_for=header_for)
    finally:
        net._sym_override.pop(proj["id"], None)
    if broken:
        listing = "\n".join(f"- {n}: {why}" for n, why in broken[:10])
        return f"❌ REJECTED: renaming breaks {len(broken)} matched function(s).\n{listing}"
    msg = message.strip() or f"rename {old} -> {new}"
    with net.store.tx() as db:
        if work is not None and guard(net, proj) != work:
            raise NetworkError('project work changed during rename checks; retry with the current symbol subject')
        if not symbol_records.rename(db, proj["id"], old, new):
            s = trial.by_name[new]
            symbol_records.save(db,
                       *(proj["id"], new, s.address, s.size, s.kind))
        # The function `old` names; by address only when that is unambiguous (Game Boy banks share CPU
        # addresses: another bank's function at the same address must keep its name)
        row = db.execute("SELECT id FROM functions WHERE project_id=? AND name=?", (proj["id"], old)).fetchone()
        if row is None and not (old in syms.by_name and syms.by_name[old].kind == "alias"):
            at = db.execute("SELECT id FROM functions WHERE project_id=? AND vram=?", (proj["id"], addr)).fetchall()
            row = at[0] if len(at) == 1 else None
        if row is not None:
            db.execute("UPDATE functions SET name=? WHERE id=?", (new, row["id"]))
        for u, header in changed.items():
            version = net._next_version(db, proj["id"])
            db.execute("INSERT INTO context_versions(project_id,version,header,agent_id,message,created_at,unit) "
                       "VALUES(?,?,?,?,?,?,?)", (proj["id"], version, header, agent.id, msg, time.time(), u))
        for fid, src in rewritten.items():
            db.execute("UPDATE functions SET matched_source=?, best_source=? WHERE id=?", (src, src, fid))
        for r in db.execute("SELECT id, best_source FROM functions WHERE project_id=? AND status='open' "
                            "AND best_source IS NOT NULL", (proj["id"],)).fetchall():
            db.execute("UPDATE functions SET best_source=? WHERE id=?", (word.sub(new, r["best_source"]), r["id"]))
        # documented assembly, and attempts at it, say the name too (but a routine's own `.local` label isn't it)
        asm_word = re.compile(rf"(?<![.\w]){re.escape(old)}\b")
        for r in db.execute("SELECT id, matched_source, best_source FROM functions WHERE project_id=? AND status IN "
                            "('documented','asm') AND (matched_source IS NOT NULL OR best_source IS NOT NULL)",
                            (proj["id"],)).fetchall():
            db.execute("UPDATE functions SET matched_source=?, best_source=? WHERE id=?",
                       (asm_word.sub(new, r["matched_source"]) if r["matched_source"] else None,
                        asm_word.sub(new, r["best_source"]) if r["best_source"] else None, r["id"]))
        net._event(db, proj["id"], agent.id, "rename", f"{old} → {new}")
    net._syms.pop(proj["id"], None)
    return f"✅ 0x{addr:08X} is now `{new}` (was `{old}`); {len(rewritten)} matched sources updated, all still match."
