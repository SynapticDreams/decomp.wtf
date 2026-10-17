"""A Game Boy project exported as RGBDS assembly: the project's names and notes in the disassembly, its matched C for
reference, and a build that remakes the game from the user's copy, byte for byte."""

import json
import subprocess
import sys

import pytest

from decompnet import toolchains
from decompnet.app.engine import RomNetwork

from .test_gb import make_rom

pytestmark = pytest.mark.skipif(toolchains.installed("mgbdis") is None or toolchains.installed("rgbds") is None,
                                reason="needs mgbdis and RGBDS (Setup installs them)")

# at 0x150: call a routine that switches banks the way games do, then loop; then padding
CODE = bytes.fromhex("cd5801" "c35001" "0000" "3e01e09bea0020c9") + b"\xff" * 16


@pytest.fixture
def exported(tmp_path):
    net = RomNetwork(tmp_path / "d.db", tmp_path / "ws")
    slug = net.import_rom(make_rom(size=0x8000, cgb=0xC0, code=CODE), confirmed=True, log=lambda *_: None)
    pid = net.project_row(slug)["id"]
    fn = net.store.one("SELECT * FROM functions WHERE project_id=? AND vram=?", pid, 0x158)
    with net.store.tx() as db:  # what agents do: a name, a note, a match
        db.execute("UPDATE functions SET name='SetBank1', status='matched', matched_source=? WHERE id=?",
                   ("void SetBank1(void) { *(volatile unsigned char *)0xff9b = 1; }", fn["id"]))
        db.execute("UPDATE symbols SET name='SetBank1' WHERE project_id=? AND name=?", (pid, fn["name"]))
        db.execute("INSERT INTO notes(project_id,function_id,agent_id,text,created_at) VALUES(?,?,?,?,?)",
                   (pid, fn["id"], None, "switches to bank 1 the way the game always does: $ff9b, then $2000", 0))
    res = net.export_rom(slug, log=lambda *_: None)
    return net, slug, res


def test_the_export_rebuilds_the_game_byte_for_byte(exported):
    net, slug, res = exported
    assert res["identical"], res["log"]
    cfg = net.cfg(net.project_row(slug))
    assert cfg["export"]["identical"] is True and cfg["export"]["matched"] == 1
    assert net.overview(slug)["exportable"]


def test_the_disassembly_has_the_projects_names_notes_and_c(exported):
    net, slug, res = exported
    from pathlib import Path
    out = Path(res["path"])
    assert "00:0158 SetBank1" in (out / "baserom.sym").read_text()
    bank0 = (out / "build" / "disassembly" / "bank_000.asm").read_text()
    assert "call SetBank1" in bank0
    lines = bank0.splitlines()
    at = next(i for i, line in enumerate(lines) if line.startswith("SetBank1:"))
    above = "\n".join(lines[at - 3:at])
    assert "; Matched in C: c/SetBank1.c" in above and "switches to bank 1" in above
    assert "0xff9b = 1" in (out / "c" / "SetBank1.c").read_text() and (out / "c" / "context.h").exists()


def test_the_tree_keeps_the_game_out_of_git(exported):
    net, slug, res = exported
    from pathlib import Path
    out = Path(res["path"])
    ignored = (out / ".gitignore").read_text().split()
    assert "build/" in ignored and "baserom.gbc" in ignored and "baserom.sym" not in ignored
    tracked = [p for p in out.rglob("*") if p.is_file() and not any(part in ("build",) for part in p.relative_to(out).parts)
               and p.name != "baserom.gbc"]
    rom = (out / "baserom.gbc").read_bytes()
    assert all(rom[0x150:0x160] not in p.read_bytes() for p in tracked)  # the game's code is in none of them


def test_the_build_refuses_another_game(exported):
    net, slug, res = exported
    from pathlib import Path
    out = Path(res["path"])
    (out / "baserom.gbc").write_bytes(make_rom(size=0x8000, cgb=0xC0, code=CODE.replace(b"\x3e\x01", b"\x3e\x02")))
    proc = subprocess.run([sys.executable, "build.py"], cwd=out, capture_output=True, text=True)
    assert proc.returncode != 0 and "isn't the version" in proc.stderr
    assert json.loads((out / "build.json").read_text())["image"] == "baserom.gbc"


def test_a_name_mgbdis_has_no_label_for_is_left_out_not_broken(tmp_path):
    """A function the project knows at an address mgbdis decodes mid-instruction (the built-in split's, say): mgbdis
    would use the name and never define it, and the build wouldn't link. It's left out, and the export says so."""
    net = RomNetwork(tmp_path / "d.db", tmp_path / "ws")
    slug = net.import_rom(make_rom(size=0x8000, cgb=0xC0, code=CODE), confirmed=True, log=lambda *_: None)
    pid = net.project_row(slug)["id"]
    with net.store.tx() as db:  # inside the call at 0x150 (cd 58 01): no instruction starts at 0x151
        db.execute("INSERT INTO functions(project_id,name,size,n_insns,target,relocs,asm,unit,vram,rom_offset,status) "
                   "VALUES(?,?,?,?,?,?,?,?,?,?,?)", (pid, "MidCall", 2, 1, b"\x58\x01", "[]", "", "bank000", 0x151, 0x151, "asm"))
    res = net.export_rom(slug, log=lambda *_: None)
    assert res["identical"], res["log"]
    assert [n for n, _ in res["fallback"]] == ["MidCall"]
