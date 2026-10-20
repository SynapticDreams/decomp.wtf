"""Which toolchain built a game, from its bytes (rom/fingerprint.py): GBDK's start-up code on the Game Boy, version by
version (gbtoolsid's checks), GBDK-2020's on the Master System and the NES, the SDSC tag, cc65's runtime. A game
none of them built is most likely assembly: the import says so, and the page starts it on the assembly track."""

from __future__ import annotations

import subprocess

import pytest

from decompnet import toolchains
from decompnet.app.engine import RomNetwork
from decompnet.rom import fingerprint

from .test_nes import make_rom as nes_rom
from .test_sms import make_rom as sms_rom

H = bytes.fromhex


def gb(**at: str) -> bytes:
    rom = bytearray(0x8000)
    for addr, pattern in at.items():
        a = int(addr[1:], 16)
        rom[a:a + len(H(pattern))] = H(pattern)
    return bytes(rom)


@pytest.mark.parametrize("marks, version", [
    ({"a20": "e9", "a28": "220d20fcc9", "a30": "1a22130d20fac9", "a157": "f3575831", "ac4": "67af6f0ea0c328",
      "acc": "f3e0ffaffbe00fc9"}, "2020.4.3.0+"),
    ({"a20": "e9", "a28": "220d20fcc9", "a30": "1a22130d20fac9", "a157": "f3575831", "ac4": "67af6f0ea0c328"}, "2020.4.2.0"),
    ({"a20": "e9", "a28": "220d20fcc9", "a30": "1a22130d20fac9", "a153": "f35731", "a100": "1851"}, "2020.4.0.4"),
    ({"a10": "80402010080402010102040810204080", "a1c2": "3e80e002afea"}, "2.0.18 - 2.1.5"),
    ({"a10": "80402010080402010102040810204080", "a1c2": "3e80e002afcd", "a1ca": "fbcd"}, "2.9.5 - 2020.3.1.0"),
    ({"a150": "f331ffcfafea", "a158": "21ffdf0e100600320520fc0d20f9cd"}, "1.x - 2.0.x"),
])
def test_gbdk_versions_from_the_game_boys_start_up_code(marks, version):
    found = fingerprint.identify("gbc", gb(**marks))
    assert found["tool"] == "GBDK" and found["version"] == version and found["language"] == "C"
    assert found["pinned"] == (version == "2020.4.3.0+") and (found["note"] == "") == found["pinned"]


def test_master_system_and_nes_builds():
    sms = sms_rom(size=0x8000, code={0x0000: H("f3ed56c38000"), 0x0080: H("31f0df")})
    assert fingerprint.identify("sms", sms)["tool"] == "GBDK-2020"
    tagged = sms_rom(size=0x8000, code={0x7FE0: b"SDSC" + H("0105") + H("18102026") + H("0060") + H("1060") + H("ffff"),
                                        0x6000: b"Someone\x00", 0x6010: b"A Game\x00"})
    found = fingerprint.identify("sms", tagged)
    assert (found["tool"], found["version"], found["author"], found["name"]) == ("SDSC tag", "1.05", "Someone", "A Game")
    assert found["language"] == "" and "WLA-DX" in found["note"]  # assemblers write the tag too: not evidence of C


SDSC = {0x7FE0: b"SDSC" + H("0105") + H("18102026") + H("0060") + H("1060") + H("ffff"),
        0x6000: b"Someone\x00", 0x6010: b"A Game\x00"}
RST08 = H("0ebff3ed69ed61fbc9")  # ld c,$bf · di · out (c),l · out (c),h · ei · ret


@pytest.mark.parametrize("platform", ["sms", "gg"])
@pytest.mark.parametrize("marks", [{0x005A: b"devkitSMS"}, {0x0008: RST08}, {0x0008: RST08, 0x005A: b"devkitSMS"}])
def test_devkitsms_start_up_code(platform, marks):
    rom = sms_rom(size=0x8000, region=4 if platform == "sms" else 7, code={0x0000: H("f3ed5631f0df1821"), **marks})
    found = fingerprint.identify(platform, rom)
    assert (found["tool"], found["language"], found["pinned"]) == ("devkitSMS", "C", False)
    assert "unsigned char" in found["note"] and "author" not in found
    named = fingerprint.identify(platform, sms_rom(size=0x8000, code={0x0000: H("f3ed5631f0df1821"), **marks, **SDSC}))
    assert (named["tool"], named["version"], named["author"], named["name"]) == ("devkitSMS", "", "Someone", "A Game")


def test_z88dk_classic_start_up_code():
    rom = sms_rom(size=0x8000, code={0x0000: H("c30001"), 0x0008: RST08 + b"Z88DK", 0x0100: H("18fe")})
    found = fingerprint.identify("sms", rom)
    assert (found["tool"], found["language"], found["pinned"]) == ("z88dk", "C", False)


@pytest.mark.parametrize("code", [
    {0x0000: H("f3ed5631f0df1821")},  # devkitSMS's first instructions alone: many games set the stack this way
    {0x0000: H("f3ed5631f0dfc30001"), 0x005A: b"devkitSMS"},  # not its `jr` to the rest of its start-up
    {0x0000: H("c30001"), 0x0008: RST08},  # z88dk's RST $08 body without its name after it
    {0x0000: H("f3ed5631f0df1821"), 0x0070: b"devkitSMS"},  # the name somewhere else
])
def test_partial_start_up_code_is_not_a_toolchain(code):
    assert fingerprint.identify("sms", sms_rom(size=0x8000, code=code)) is None
    cc65 = nes_rom(prg_units=2, code={0x100: H("a001b102aa88b102e602f005e602f00360e602e60360")}, vectors=(0x8000,) * 3)
    found = fingerprint.identify("nes", cc65)
    assert found["tool"] == "cc65" and not found["pinned"] and "assembly" in found["note"]
    gbdk = nes_rom(prg_units=2, code={0x4000: H("78a2ff9aa9008d9fc38d00208d0120")}, vectors=(0xC000, 0xC000, 0xC000))
    assert fingerprint.identify("nes", gbdk)["tool"] == "GBDK-2020"
    assert fingerprint.identify("nes", nes_rom(prg_units=2, code={0: H("4c0080")}, vectors=(0x8000,) * 3)) is None
    assert fingerprint.identify("gbc", gb()) is None and fingerprint.identify("sms", sms_rom(size=0x8000)) is None


_LCC = toolchains.path("gbdk-2020") / "gbdk" / "bin" / "lcc"


@pytest.mark.skipif(not _LCC.exists(), reason="needs GBDK-2020")
@pytest.mark.parametrize("port, platform", [("sm83:gb", "gb"), ("z80:sms", "sms"), ("mos6502:nes", "nes")])
def test_the_pinned_gbdks_own_builds_are_told(tmp_path, port, platform):
    (tmp_path / "m.c").write_text("#include <gbdk/platform.h>\nunsigned char x;\nvoid main(void) { while (1) { x++; vsync(); } }\n")
    out = tmp_path / f"m.{platform}"
    subprocess.run([str(_LCC), f"-m{port}", "-o", str(out), "m.c"], cwd=tmp_path, check=True, capture_output=True)
    found = fingerprint.identify(platform, out.read_bytes())
    assert found and found["tool"].startswith("GBDK") and found["pinned"], found


def test_the_import_says_what_built_a_game(tmp_path):
    net = RomNetwork(tmp_path / "d.db", tmp_path / "ws")
    rom = tmp_path / "game.sms"
    rom.write_bytes(sms_rom(size=0x8000, code={0x0000: H("f3ed56c38000"), 0x0080: H("31f0df76")}))
    lines: list[str] = []
    slug = net.import_rom(rom, confirmed=True, log=lines.append)
    assert any(line.startswith("built with GBDK-2020 (C)") for line in lines)
    assert net.overview(slug)["built_with"]["tool"] == "GBDK-2020"
    other = tmp_path / "other.sms"
    other.write_bytes(sms_rom(size=0x8000, code={0x0000: H("c30001"), 0x0100: H("18fe")}))
    slug2 = net.import_rom(other, confirmed=True, log=lines.append)
    assert net.overview(slug2)["built_with"] is None and any("hand-written assembly" in line for line in lines)


def test_a_devkitsms_import_starts_with_unsigned_char_and_a_gbdk_one_keeps_signed(tmp_path):
    net = RomNetwork(tmp_path / "d.db", tmp_path / "ws")
    devkit = tmp_path / "devkit.sms"
    devkit.write_bytes(sms_rom(size=0x8000, code={0x0000: H("f3ed5631f0df1821"), 0x005A: b"devkitSMS"}))
    compiler = net.cfg(net.project_row(net.import_rom(devkit, confirmed=True, log=lambda *_: None)))["compiler"]
    assert compiler["flags"] == [] and "without --fsigned-char" in compiler["note"]
    gbdk = tmp_path / "gbdk.sms"
    gbdk.write_bytes(sms_rom(size=0x8000, code={0x0000: H("f3ed56c38000"), 0x0080: H("31f0df76")}))
    assert net.cfg(net.project_row(net.import_rom(gbdk, confirmed=True, log=lambda *_: None)))["compiler"]["flags"] == \
        ["--fsigned-char"]


@pytest.mark.skipif(not _LCC.exists(), reason="needs GBDK-2020")
def test_char_signedness_changes_what_sdcc_writes():
    from decompnet.rom import gb_build

    source = "char half(char c) { return c >> 1; }\n"
    signed = gb_build.compile_function(source, "half", arch="z80", opt=["--fsigned-char"]).code
    unsigned = gb_build.compile_function(source, "half", arch="z80", opt=[]).code
    assert (signed, unsigned) == (H("cb2fc9"), H("cb3fc9"))  # sra a / srl a
