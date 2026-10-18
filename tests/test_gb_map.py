"""Telling a Game Boy game's code from its data (rom/gb_trace.py): the code followed with the banks it maps, what it
didn't reach sorted into padding, data and code-like, and mgbdis handed the result (rom/gb_mgbdis.py).

The cartridges are synthetic (tests/test_gb.make_rom): a valid header, and code placed where each case needs it."""

from __future__ import annotations

import json

import pytest

from decompnet.rom import gb, gb_mgbdis, gb_trace
from tests.test_gb import make_rom

needs_tools = pytest.mark.skipif(not gb_mgbdis.available(), reason="needs mgbdis and RGBDS")


def rom_with(parts: dict[int, str], size: int = 0x10000, cart: int = 0x19) -> bytes:
    """A cartridge (MBC5 by default) with `parts` ({flat offset: hex bytes}) written in; the entry point jumps to
    0x150."""
    rom = bytearray(make_rom(size=size, cart=cart, size_code=0x01 if size == 0x10000 else 0x00))
    for at, hexes in parts.items():
        code = bytes.fromhex(hexes.replace(" ", ""))
        rom[at:at + len(code)] = code
    rom[0x14D] = gb.header_checksum(rom)
    return bytes(rom)


# ------------------------------------------------------------------ following the code

def test_a_call_into_the_window_reaches_the_bank_the_code_mapped():
    data = rom_with({0x150: "3e02 ea0020 cd0040 18fe",  # ld a,2 · ld ($2000),a · call $4000 · jr $
                     0x8000: "3e01 c9"})  # bank 2: ld a,1 · ret
    found = gb_trace.follow(data)
    assert 0x8000 in found.starts  # bank 2's 0x4000
    assert 0x4000 not in found.starts  # not bank 1's
    assert found.code.get(0x8000) == 2


def test_a_bank_switcher_maps_the_bank_its_caller_passes():
    data = rom_with({0x200: "ea0020 c9",  # ld ($2000),a · ret: maps the A it's given
                     0x150: "3e03 cd0002 cd1040 18fe",  # ld a,3 · call $0200 · call $4010 · jr $
                     0xC010: "af c9"})  # bank 3, 0x4010
    found = gb_trace.follow(data)
    assert 0x200 in found.switchers
    assert 0xC010 in found.starts


def test_banked_code_calling_the_window_stays_in_its_own_bank():
    data = rom_with({0x150: "3e02 ea0020 cd0040 18fe",
                     0x8000: "cd2040 c9",  # bank 2: call $4020 (its own bank) · ret
                     0x8020: "af c9"})
    found = gb_trace.follow(data)
    assert 0x8020 in found.starts and 0x4020 not in found.starts


def test_a_function_that_indexes_a_jump_table_names_its_handlers():
    data = rom_with({0x150: "af cd0003 18fe",  # xor a · call $0300 · jr $
                     # ld hl,$0310 · add a,a · ld e,a · ld d,0 · add hl,de · ld a,(hl+) · ld h,(hl) · ld l,a · jp hl
                     0x300: "211003 87 5f 1600 19 2a 66 6f e9",
                     0x310: "2003 3003",  # dw $0320, $0330
                     0x320: "3e01 c9", 0x330: "3e02 c9"})
    found = gb_trace.follow(data)
    assert found.starts[0x320][1] == "table" and found.starts[0x330][1] == "table"
    assert found.tables == {0x310: 2}
    assert (0x310, 4, "table", "a table of 2 handler addresses") in gb_trace.regions(data, found)


def test_a_dispatcher_reached_through_an_rst_reads_the_table_after_the_call():
    data = rom_with({0x28: "c30005",  # rst $28: jp $0500
                     0x500: "e1 87 5f 1600 19 2a 66 6f e9",  # pop hl · (index the words after the call) · jp hl
                     0x150: "af ef 2005 3005",  # xor a · rst $28 · dw $0520, $0530
                     0x520: "3e01 c9", 0x530: "3e02 c9"})
    found = gb_trace.follow(data)
    assert 0x500 in found.takes_return and 0x500 in found.dispatchers
    assert {0x520, 0x530} <= set(found.starts)
    assert found.tables.get(0x152) == 2
    assert 0x152 not in found.code and 0x154 not in found.code  # the words aren't decoded as code


def test_a_handler_stored_by_a_setter_through_its_hl_argument_is_found():
    data = rom_with({0x150: "212004 cd0004 18fe",  # ld hl,$0420 · call SetState · jr $
                     0x400: "7d ea10c8 7c ea11c8 c9",  # SetState: ld a,l · ld ($c810),a · ld a,h · ld ($c811),a · ret
                     0x420: "3e05 c9"})
    found = gb_trace.follow(data)
    assert found.setters.get(0x400) == {"hl"}
    assert found.starts.get(0x420, (0, ""))[1] == "pointer"


def test_a_word_stored_to_ram_in_one_function_is_a_pointer():
    data = rom_with({0x150: "3e20 ea10c8 3e04 ea11c8 18fe",  # ld a,$20 · ld ($c810),a · ld a,$04 · ld ($c811),a · jr $
                     0x420: "3e05 c9"})
    found = gb_trace.follow(data)
    assert 0x420 in found.starts


def test_a_function_that_jumps_into_ram_returns():
    """`jp $ff80` (a routine copied to HRAM) returns for it, so what follows a call to it is still code."""
    data = rom_with({0x150: "cd0006 cd1006 18fe",
                     0x600: "2100c0 c380ff",  # ld hl,$c000 · jp $ff80
                     0x610: "af c9"})
    found = gb_trace.follow(data)
    assert 0x600 in found.returns and 0x610 in found.starts


def test_a_run_of_zero_bytes_isnt_followed_as_nops():
    data = rom_with({0x150: "cd0002 18fe"})  # call $0200, where there is nothing but zeros
    found = gb_trace.follow(data)
    assert not any(0x200 < flat < 0x4000 for flat in found.code)


def test_reached_code_no_function_covers_starts_one():
    """The entry point jumps over the cartridge header to 0x150: that code starts a function of its own."""
    data = rom_with({0x150: "af c9"})
    found = gb_trace.follow(data)
    assert 0x150 in found.starts


# ------------------------------------------------------------------ what wasn't reached

def test_unreached_bytes_are_padding_data_or_left_as_code():
    data = rom_with({0x150: "18fe",
                     0x4100: "d3 dd e3 eb 52 5b 64 6d",  # no instructions, registers loaded with themselves: data
                     0x4300: "cd0844 cd0042 c9",  # code nothing reached: call $4408 · call $4200 · ret
                     0x4200: "3e01 c9",
                     0x4400: "d3 dd e3 eb 52 5b 64 6d 3e02 c9"})  # data running straight into code called above
    found = gb_trace.follow(data)
    regs = gb_trace.regions(data, found)
    data_at = [(lo, lo + n) for lo, n, kind, _ in regs if kind == "data"]
    covered = lambda a: any(lo <= a < hi for lo, hi in data_at)  # noqa: E731
    assert covered(0x4100) and covered(0x4400) and covered(0x4407)
    assert not covered(0x4408) and not covered(0x4200) and not covered(0x4300)
    assert any(kind == "padding" and lo <= 0x4000 < lo + n for lo, n, kind, _ in regs)  # the zeros before 0x4100
    assert not any(lo < 0x150 + 2 and 0x150 < lo + n for lo, n, *_ in regs)  # reached code is never a region


def test_hints_mark_data_and_add_entries():
    data = rom_with({0x150: "18fe", 0x4200: "3e01 c9", 0x4300: "3e02 c9"})
    hints = {"entries": {0x4200: 0x4200}, "data": [(0x4300, 3)]}
    found = gb_trace.follow(data, hints)
    assert 0x4200 in found.starts
    assert (0x4300, 3, "hint", "marked as data") in gb_trace.regions(data, found, hints)


def test_the_symbol_file_has_code_blocks_at_starts_and_data_blocks():
    data = rom_with({0x150: "3e02 ea0020 cd0040 18fe", 0x8000: "3e01 c9", 0x8100: "d3 dd e3 eb 52 5b 64 6d"})
    found = gb_trace.follow(data)
    regs = gb_trace.regions(data, found)
    sym = gb_trace.sym_text(data, found, regs)
    assert "02:4000 Call_002_4000" in sym and "02:4000 .code:" in sym
    assert any(line.startswith("02:41") and ".data:" in line for line in sym.splitlines())
    assert not any(line.startswith("00:0000 ") and ".data" not in line for line in sym.splitlines())  # mgbdis names them


# ------------------------------------------------------------------ mgbdis with the map

@needs_tools
def test_the_mapped_split_drops_functions_that_were_data_and_rebuilds_the_rom(tmp_path):
    """A table in bank 1 holds a `call`-like CD byte: mgbdis alone takes its target for a function; with the map it
    shows the table as data and no function starts there. The rebuild stays byte-identical."""
    data = rom_with({0x150: "3e01 ea0020 cd0040 18fe",
                     0x4000: "af c9",
                     0x4100: "cd5041 d3 dd e3 eb 52 5b 64 6d",  # a fake `call $4150` in data
                     0x4150: "d3 dd e3 eb 52 5b 64 6d"})
    path = tmp_path / "game.gb"
    path.write_bytes(data)
    fns, meta = gb_mgbdis.split(path, tmp_path)
    assert meta["faithful"] and meta["mapped"]
    starts = {f.rom for f in fns}
    assert 0x4000 in starts and 0x4150 not in starts
    assert any(lo <= 0x4100 < lo + n for lo, n, kind, _ in meta["regions"] if kind == "data")
    assert all(not (f.rom <= 0x4100 < f.rom + f.size) for f in fns)  # no function runs into the data


@needs_tools
def test_a_map_that_breaks_the_rebuild_falls_back_to_the_plain_split(tmp_path, monkeypatch):
    data = rom_with({0x150: "af c9"})
    path = tmp_path / "game.gb"
    path.write_bytes(data)
    real = gb_mgbdis._disassemble

    def broken(rom, tmp, log=lambda *_: None):
        out, symbols, faithful, rebuilt = real(rom, tmp, log)
        sym = rom.with_suffix(".sym")
        mapped = sym.is_file() and "made by decomp.wtf" in sym.read_text()
        return out, symbols, faithful and not mapped, rebuilt

    monkeypatch.setattr(gb_mgbdis, "_disassemble", broken)
    fns, meta = gb_mgbdis.split(path, tmp_path)
    assert meta["faithful"] and not meta["mapped"] and meta["regions"] == []


@needs_tools
def test_a_symbol_file_next_to_the_rom_comes_after_the_map(tmp_path):
    data = rom_with({0x150: "cd0002 18fe", 0x200: "af c9"})
    path = tmp_path / "game.gb"
    path.write_bytes(data)
    path.with_suffix(".sym").write_text("00:0200 ClearA\n")
    fns, meta = gb_mgbdis.split(path, tmp_path)
    assert meta["faithful"]
    assert any(f.name == "ClearA" and f.rom == 0x200 for f in fns)


# ------------------------------------------------------------------ the project keeps the map

@needs_tools
def test_import_keeps_the_data_regions_and_splitting_again_reports_them(tmp_path):
    from decompnet.app.engine import RomNetwork

    net = RomNetwork(tmp_path / "app.db", tmp_path / "work")
    net.auto_install_tools = False
    rom = tmp_path / "game.gb"
    rom.write_bytes(rom_with({0x150: "3e01 ea0020 cd0040 18fe", 0x4000: "af c9",
                              0x4100: "cd5041 d3 dd e3 eb 52 5b 64 6d"}))
    slug = net.import_rom(rom, confirmed=True, log=lambda *_: None)
    proj = net._project(slug)
    regions = net.store.all("SELECT * FROM data_regions WHERE project_id=?", proj["id"])
    assert any(r["kind"] == "data" and r["rom_offset"] <= 0x4100 < r["rom_offset"] + r["size"] for r in regions)
    assert json.loads(proj["config"])["splitter"] == "mgbdis"
    out = net.resplit_banked(slug, log=lambda *_: None)
    assert out["data_after"] == out["data_before"] == sum(r["size"] for r in regions)
    assert out["kept"] == out["before"] == out["after"]
    net.remove_project(slug)
    assert not net.store.all("SELECT * FROM data_regions WHERE project_id=?", proj["id"])
