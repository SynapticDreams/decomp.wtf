"""Project overview and banked range presentation, separate from engine orchestration."""
import json
from .. import toolchains
from ..rom import detect
from . import sms_progress, sms_export_state


def build(net, slug: str, proj) -> dict:
    if (fork := net.fork_slug(slug)):
        return net.forks.overview(fork)
    cfg = net.cfg(proj)
    from .engine import BANKED_ARCHS, PLATFORM_COMPILERS, SHORT_NAMES
    sms = sms_progress.read(net, proj, cfg) if cfg.get('platform') in ('sms', 'gg') else None
    agg = net.store.one(
        "SELECT COUNT(*) AS total, SUM(status='matched') AS matched, SUM(size) AS bytes, "
        "SUM(CASE WHEN status='matched' THEN size ELSE 0 END) AS matched_bytes, SUM(attempts) AS attempts, "
        "SUM(status='asm') AS asm, SUM(CASE WHEN status='asm' THEN size ELSE 0 END) AS asm_bytes, "
        "SUM(status='documented') AS documented, SUM(CASE WHEN status='documented' THEN size ELSE 0 END) AS documented_bytes "
        "FROM functions WHERE project_id=?", proj["id"])
    tc = toolchains.get(cfg["compiler"]["toolchain"])
    from ..rom.sms_profile import describe
    result = {
        "slug": proj["slug"], "title": proj["name"], "description": proj["description"],
        "platform": cfg.get("platform", "n64"), "platform_name": detect.PLATFORMS.get(cfg.get("platform", "n64"), ""),
        "sms_profile": describe(cfg),
        "compilers": PLATFORM_COMPILERS.get(cfg.get("platform", "n64"), []),
        "rom": {k: cfg["rom"].get(k) for k in ("title", "game_code", "region", "size", "sha1", "byte_order", "compiler_guess")},
        # what built a banked game, as its bytes say (rom/fingerprint.py): None, most likely assembly; absent, not read
        "built_with": cfg.get("built_with", False) if cfg.get("arch") in BANKED_ARCHS else False,
        "compiler": {"toolchain": tc.id, "name": SHORT_NAMES.get(tc.id, tc.name), "flags": cfg["compiler"]["flags"],
                     "aspsx": cfg["compiler"].get("aspsx", ""),
                     "probe": cfg.get("compiler_probe"),
                     "libraries": cfg.get("psyq_libraries"),
                     "small_data": cfg.get("small_data"),
                     "units": cfg["compiler"].get("units", {}),
                     "unit_names": [r["unit"] for r in net.store.all(
                         "SELECT DISTINCT unit FROM functions WHERE project_id=? ORDER BY unit", proj["id"])],
                     "installed": toolchains.installed(tc.id) is not None, "proprietary": tc.proprietary,
                     "supported": tc.supported, "wsl": tc.via_wsl,
                     "why": None if tc.supported else toolchains.unsupported_cpu()},
        "functions": agg["total"] or 0, "matched": agg["matched"] or 0, "bytes": agg["bytes"] or 0,
        "matched_bytes": agg["matched_bytes"] or 0, "attempts": agg["attempts"] or 0,
        # set aside: assembly no compiler makes, or what the split took for code (see handwritten.py)
        "asm": agg["asm"] or 0, "asm_bytes": agg["asm_bytes"] or 0,
        # the assembly track (Game Boy): hand-written routines documented in assembly, apart from C matches
        "documented": agg["documented"] or 0, "documented_bytes": agg["documented_bytes"] or 0,
        "mapped": sms["mapped"] if sms else net._mapped(proj, cfg) if (proj["arch"] or "") in BANKED_ARCHS else None,
        "context_version": net._context(proj["id"])["version"],
        "folder": proj["root"],
        "export": cfg.get("export"),
        "exportable": not cfg.get("mapping") and cfg.get("platform", "n64") in ("n64", "psx", "ps2", "gba", "gb", "gbc",
                                                                              "sms", "gg", "nes"),
        "mapping": {"version": 1, "regions": list(cfg["mapping"]["regions"])} if cfg.get("mapping") else None,
        "room": net._room_info(proj["slug"]),
    }
    if sms:
        result.update(sms['totals'], sms_progress=sms['metrics'])
        result['sms_progress']['input'], result['export'] = sms_export_state.present(net, proj, cfg)
    return result


def mapped(net, proj, cfg: dict) -> dict:
    """How much of a banked game's ROM the project knows what it is: code (its functions, but for what's set aside
    as not code), data (tables, padding, operands, bytes the code never reaches), and how many hand-written
    routines are left to document."""
    from .engine import ASM_ARCHS
    if cfg.get('platform') in ('sms', 'gg'):
        return sms_progress.read(net, proj, cfg)['mapped']
    rows = net.store.all("SELECT status, size, meta FROM functions WHERE project_id=?", proj["id"])
    code = sum(r["size"] or 0 for r in rows if r["status"] != "asm" or net.asm_track(r))
    data = net.store.one("SELECT COALESCE(SUM(size), 0) AS n FROM data_regions WHERE project_id=?", proj["id"])["n"]
    size = int((cfg.get("rom") or {}).get("size") or 0)
    return {"rom": size, "code": code, "data": data,
            "to_document": sum(1 for r in rows if r["status"] == "asm" and net.asm_track(r))
            if proj["arch"] in ASM_ARCHS else 0}


def list_projects(net):
    rows = net.store.all('SELECT p.*,COUNT(f.id) AS total,SUM(f.status=\'matched\') AS matched,SUM(f.size) AS bytes, '
                         "SUM(CASE WHEN f.status='matched' THEN f.size ELSE 0 END) AS matched_bytes "
                         'FROM projects p LEFT JOIN functions f ON f.project_id=p.id GROUP BY p.id ORDER BY p.slug')
    if not rows:
        return 'No projects yet.'
    out = []
    for row in rows:
        cfg = json.loads(row['config'])
        pct, scope = 100 * (row['matched_bytes'] or 0) / (row['bytes'] or 1), 'of code'
        if cfg.get('platform') in ('sms', 'gg'):
            references = sms_progress.read(net, row, cfg)['metrics']['c_reference']
            pct = 100 * references['bytes'] / (references['eligible_bytes'] or 1)
            scope = 'of C candidates, stored byte references; not linked'
        legal = cfg.get('legal', {})
        out.append(f"- {row['slug']}: {row['name']} [{row['arch']}] — {row['matched'] or 0}/{row['total']} functions "
                   f"matched ({pct:.1f}% {scope}); legal basis: {legal.get('basis')}, contributions licensed "
                   f"{legal.get('license')}\n  {row['description']}".rstrip())
    return '\n'.join(out)


def status_dimensions(net, result):
    for row in result['projects']:
        proj = net.project_row(row['slug'])
        cfg = net.cfg(proj)
        if cfg.get('platform') in ('sms', 'gg'):
            measured = sms_progress.read(net, proj, cfg)
            row.update(measured['totals'], sms_progress=measured['metrics'])
    return result
