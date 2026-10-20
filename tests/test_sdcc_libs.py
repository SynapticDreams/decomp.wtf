"""SDCC library recognition (rom/sdcc_libs.py, app/sdcc_libraries.py): patterns from ASxxxx objects with their
relocated bytes as wildcards, unique whole-pattern hits only, and an apply that names and sets aside library functions
without touching claimed, accepted or renamed work. Ground truth for the real libraries is the pinned GBDK's own link
map of a game it built."""

from __future__ import annotations

import base64
import re
import subprocess

import pytest

from decompnet import toolchains
from decompnet.app.engine import RomNetwork
from decompnet.network import NetworkError
from decompnet.rom import sdcc_libs

from .test_sms import make_rom

LCC = toolchains.path("gbdk-2020") / "gbdk" / "bin" / "lcc"
needs_gbdk = pytest.mark.skipif(not LCC.exists(), reason="needs GBDK-2020")

OBJECT = """XL4
H 3 areas 2 global symbols
M sample
S .__.ABS. Def00000000
A _CODE size D flags 0 addr 0
S _first Def00000000
S _second Def00000007
A _DATA size 2 flags 0 addr 0
S _counter Def00000000
T 00 00 00 00 21 00 00 7E C3 00 00
R 00 00 00 00 00 05 01 00 02 09 00 00
T 07 00 00 00 3E 00 00 C9 18 FE
R 00 00 00 00 09 05 01 00
"""
# Sizes and offsets are hex. _first: ld hl,_counter (area word) · ld a,(hl) · jp _ext (symbol word); _second at 7:
# ld a,#<_counter (an R_BYT2 byte: two record bytes, one output byte) · ret · jr $ · nop: 13 bytes in all


def rel(text=OBJECT):
    return text.replace("T 07 00 00 00 3E 00 00 C9 18 FE", "T 07 00 00 00 3E 00 00 C9 18 FE 00")


def test_relocated_bytes_become_wildcards_and_r_byt2_bytes_collapse_to_one():
    (function,) = sdcc_libs.parse_rel(rel(), "test.lib")
    assert (function.library, function.module, function.area) == ("test.lib", "sample", "_CODE")
    assert function.pattern == (0x21, None, None, 0x7E, 0xC3, None, None, 0x3E, None, 0xC9, 0x18, 0xFE, 0x00)
    assert function.labels == (("_first", 0), ("_second", 7))


@pytest.mark.parametrize("change, error", [
    (lambda t: t.replace("R 00 00 00 00 09 05 01 00", "R 00 00 00 00 41 05 01 00"), "unsupported relocation mode"),
    (lambda t: t.replace("size D", "size 14"), "don't cover"),
    (lambda t: t.replace("XL4", "XH4"), "XL4"),
    (lambda t: t.replace("R 00 00 00 00 09 05 01 00", "R 00 00 07 00"), "undefined area"),
])
def test_objects_that_cant_be_read_exactly_are_refused(change, error):
    with pytest.raises(ValueError, match=error):
        sdcc_libs.parse_rel(change(rel()))


def test_ar_archives_with_long_names_are_read_and_bad_members_reported():
    long_name = "a_module_with_a_long_name.rel"
    names = f"{long_name}/\n".encode()
    body = rel().encode()

    def member(name: str, data: bytes) -> bytes:
        return f"{name:<16}{0:<12}{0:<6}{0:<6}{644:<8}{len(data):<10}`\n".encode() + data + (b"\n" if len(data) & 1 else b"")
    archive = b"!<arch>\n" + member("//", names) + member("/0", body) + member("bad.rel/", b"not an object")
    functions, skipped = sdcc_libs.from_library("x.lib", archive)
    assert [(f.module, f.labels[0][0]) for f in functions] == [(long_name, "_first")]
    assert skipped == ["bad.rel: expected an SDCC/ASxxxx XL4 object"]
    with pytest.raises(ValueError, match="ar archive"):
        sdcc_libs.ar_members(b"not an archive")


def fn(pattern: bytes | tuple, *labels, module="m"):
    pattern = tuple(pattern)
    return sdcc_libs.Function("lib", module, "_CODE", pattern, tuple(labels) or (("_f", 0),))


BODY = bytes(range(0x40, 0x54))  # 20 concrete bytes


def test_only_a_unique_whole_pattern_hit_counts():
    image = bytes(0x100) + BODY + bytes(0x40)
    hit = sdcc_libs.scan(image, [fn(BODY[:4] + bytes([0]) + BODY[5:])])  # (a differing concrete byte: no hit)
    assert hit["hits"] == []
    found = sdcc_libs.scan(image, [fn((*BODY[:4], None, *BODY[5:]), ("_f", 0), ("_g", 8))])
    assert [(h["rom_offset"], h["name"], h["matched_end"]) for h in found["hits"]] == [(0x100, "f", 0x114), (0x108, "g", 0x114)]
    twice = sdcc_libs.scan(image + BODY, [fn(BODY)])
    assert twice["hits"] == []


def test_weak_patterns_are_skipped_and_aliases_and_conflicts_are_told_apart():
    image = bytes(0x100) + BODY
    assert sdcc_libs.scan(image, [fn(BODY[:10])])["weak_skipped"] == 1
    aliases = sdcc_libs.scan(image, [fn(BODY, ("_memcpy", 0), ("___memcpy", 0))])["hits"]
    assert [(h["name"], h["symbol"], h["aliases"]) for h in aliases] == [("memcpy", "_memcpy", ["___memcpy"])]
    clash = sdcc_libs.scan(image, [fn(BODY, ("_a", 0), module="one"), fn(BODY, ("_b", 0), module="two")])
    assert clash["hits"] == [] and clash["conflicts"] == [{"rom_offset": 0x100, "names": ["_a", "_b"]}]
    assert sdcc_libs.c_name("__mulint") == "_mulint" and sdcc_libs.c_name("_atoi") == "atoi"


SOURCE = """#include <gbdk/platform.h>
#include <string.h>
#include <stdlib.h>
char buf[32];
int n;
void main(void) {
    strcpy(buf, "hello");
    n = strlen(buf) * atoi("12") / 3;
    memset(buf, n, 8);
    while (1) { n += strncmp(buf, "he", 2); vsync(); }
}
"""


def built(tmp_path, platform: str) -> tuple[bytes, dict[int, set[str]]]:
    (tmp_path / "m.c").write_text(SOURCE)
    subprocess.run([str(LCC), f"-mz80:{platform}", "-Wl-m", "-o", f"m.{platform}", "m.c"], cwd=tmp_path, check=True,
                   capture_output=True)
    names: dict[int, set[str]] = {}
    for address, name in re.findall(r"\b([0-9A-F]{8})  (\S+)", (tmp_path / "m.map").read_text()):
        names.setdefault(int(address, 16), set()).add(name)
    return (tmp_path / f"m.{platform}").read_bytes(), names


@needs_gbdk
@pytest.mark.parametrize("platform", ["sms", "gg"])
def test_gbdk_libraries_name_what_its_own_link_map_says(tmp_path, platform):
    from decompnet.app.sdcc_libraries import gbdk_libraries

    image, truth = built(tmp_path, platform)
    functions = [f for name, data in gbdk_libraries(platform) for f in sdcc_libs.from_library(name, data)[0]]
    report = sdcc_libs.scan(image, functions)
    assert len(report["hits"]) >= 10 and report["conflicts"] == []
    for hit in report["hits"]:  # (the map truncates long names)
        names = truth.get(hit["rom_offset"], set())
        assert any(symbol.startswith(name) for symbol in {hit["symbol"], *hit["aliases"]} for name in names), hit
    found = {h["symbol"] for h in report["hits"]}
    assert {"_memset", "_atoi", "_strncmp", "__mulint"} <= found


@needs_gbdk
def test_apply_names_and_sets_aside_only_unsettled_library_functions(tmp_path):
    image, _truth = built(tmp_path, "sms")
    net = RomNetwork(tmp_path / "d.db", tmp_path / "ws")
    net.auto_install_tools = False
    slug = net.import_rom(image, name="m.sms", confirmed=True, log=lambda *_: None)
    net.sms.configure(slug, "sega", "annotated-original", "GBDK-2020's start-up code sets up the Sega mapper's slots.")
    pid = net.project_row(slug)["id"]
    rows = {r["rom_offset"]: r for r in net.store.all("SELECT * FROM functions WHERE project_id=?", pid)}
    hits = {h["symbol"]: h["rom_offset"] for h in net.identify_sdcc_libraries(slug, log=lambda *_: None)["hits"]}
    memset, atoi, strncmp = rows[hits["_memset"]], rows[hits["_atoi"]], rows[hits["_strncmp"]]
    agent = net.authenticate(net.register_agent("worker"))
    net.claim(agent, slug, memset["name"])  # claimed work stays as it is
    with net.store.tx() as db:
        db.execute("UPDATE functions SET status='documented', matched_source=? WHERE id=?",
                   ("; Accepted documented source stays as it is.\n", atoi["id"]))
    assert net.store.all("SELECT name FROM functions WHERE project_id=? AND status='asm'", pid) == []
    report = net.identify_sdcc_libraries(slug, apply=True, log=lambda *_: None)
    assert report["applied"] >= 5 and report["renamed"] >= 5
    after = {r["id"]: r for r in net.store.all("SELECT * FROM functions WHERE project_id=?", pid)}
    assert after[strncmp["id"]]["name"] == "strncmp" and after[strncmp["id"]]["status"] == "asm"
    assert "recognized SDCC library function strncmp" in after[strncmp["id"]]["meta"]
    assert after[memset["id"]]["name"] == memset["name"] and after[memset["id"]]["status"] == memset["status"]
    assert after[atoi["id"]]["status"] == "documented" and after[atoi["id"]]["name"] == atoi["name"]
    assert net.overview(slug)["compiler"]["sdcc_libraries"]["applied"] == report["applied"]


@needs_gbdk
def test_added_library_files_are_validated_cached_and_reused(tmp_path):
    image, _truth = built(tmp_path, "sms")
    net = RomNetwork(tmp_path / "d.db", tmp_path / "ws")
    net.auto_install_tools = False
    slug = net.import_rom(image, name="m.sms", confirmed=True, log=lambda *_: None)
    with pytest.raises(NetworkError, match="no SDCC code areas"):
        net.identify_sdcc_libraries(slug, [{"name": "empty.rel", "data": base64.b64encode(b"XL4\n").decode()}])
    with pytest.raises(NetworkError, match="base64"):
        net.identify_sdcc_libraries(slug, [{"name": "x.lib", "data": "!!"}])
    assert not (net.workspace / ".decomp" / "sdcc-libraries").exists()
    library = toolchains.path("gbdk-2020") / "gbdk" / "lib" / "z80" / "z80.lib"
    report = net.identify_sdcc_libraries(slug, [{"name": "copy.lib", "data": base64.b64encode(library.read_bytes()).decode()}],
                                         log=lambda *_: None)
    assert "copy.lib" in report["libraries"]
    assert "copy.lib" in net.identify_sdcc_libraries(slug, log=lambda *_: None)["libraries"]  # (kept locally)


def test_only_sms_and_gg_rom_projects_are_scanned(tmp_path):
    from .test_gb import make_rom as gb_rom

    net = RomNetwork(tmp_path / "d.db", tmp_path / "ws")
    net.auto_install_tools = False
    slug = net.import_rom(gb_rom(), name="g.gb", confirmed=True, log=lambda *_: None)
    with pytest.raises(NetworkError, match="Master System and Game Gear"):
        net.identify_sdcc_libraries(slug)
    sms = net.import_rom(make_rom(), name="s.sms", confirmed=True, log=lambda *_: None)
    assert net.identify_sdcc_libraries(sms, log=lambda *_: None)["hits"] == []
