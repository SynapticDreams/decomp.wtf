"""Game Gear ports $00-$06 in its own mode (rom/sms_effects.py): Start/region, link and PSG stereo registers that
never reach memory control. A Master System, or a Game Gear cartridge running in Master System mode, decodes them as
possible $3E mirrors, so a write there still leaves the bus source unresolved."""

from __future__ import annotations

import pytest

from decompnet.rom import sms, sms_effects, sms_trace

from .test_sms import make_rom

SIZE = 0x20000
BANK5 = {0x14000: bytes.fromhex("3e07c9")}  # bank 5 at 0x8000: ld a,7 · ret


@pytest.mark.parametrize("text, bc", [("out ($00), a", None), ("out ($02), a", None), ("out ($06), a", None),
                                      ("out (c), a", 0x0106), ("outi", 0x0004), ("otir", 0x2002)])
def test_game_gear_register_ports_preserve_the_source_only_in_game_gear_mode(text, bc):
    assert sms_effects.port_may_change_source(text, bc) is True
    assert sms_effects.port_may_change_source(text, bc, game_gear=True) is False


@pytest.mark.parametrize("text, bc", [("out ($3e), a", None), ("out ($08), a", None), ("out ($3c), a", None),
                                      ("out (c), a", None), ("out (c), a", 0x003E), ("otir", None)])
def test_memory_control_its_possible_mirrors_and_unknown_ports_stay_unresolved_on_game_gear(text, bc):
    assert sms_effects.port_may_change_source(text, bc, game_gear=True) is True


def test_known_device_ports_preserve_the_source_on_both_consoles():
    for text in ("out ($bf), a", "out ($be), a", "out ($7f), a", "out ($3f), a"):
        assert sms_effects.port_may_change_source(text) is False
        assert sms_effects.port_may_change_source(text, game_gear=True) is False


def _rom(region: int) -> bytes:
    vectors = {at: b"\xc9" for at in sms.VECTORS if at}
    # ld a,5 · ld ($ffff),a · ld a,$ff · out ($06),a · call $8000 · jr $
    code = {0x0000: bytes.fromhex("c30001"), 0x0100: bytes.fromhex("3e05" "32ffff" "3eff" "d306" "cd0080" "18fe")}
    return make_rom(size=SIZE, region=region, code={**vectors, **code, **BANK5})


def test_a_stereo_write_keeps_the_mapped_bank_for_the_next_call_on_game_gear():
    found = sms_trace.Tracer(_rom(6), hints={"platform": "gg"}).follow({0: (0, "vector")})
    assert found.starts.get(0x14000) == (0x8000, "call")
    assert 0 not in found.unresolved


def test_the_same_write_on_a_master_system_leaves_the_bank_unresolved():
    found = sms_trace.Tracer(_rom(4), hints={"platform": "sms"}).follow({0: (0, "vector")})
    assert 0x14000 not in found.starts
    assert "explicit memory or source-control write is unqualified" in found.unresolved[0]


def test_the_split_reads_the_platform_from_the_cartridge_unless_the_project_says(tmp_path):
    gg = tmp_path / "game.gg"
    gg.write_bytes(_rom(6))
    assert any(f.rom == 0x14000 and f.vram == 0x8000 for f in sms.split(gg, tmp_path))
    master = tmp_path / "game.sms"
    master.write_bytes(_rom(4))
    assert not any(f.rom == 0x14000 for f in sms.split(master, tmp_path))
    # a Game Gear cartridge with a Master System header runs in Master System mode
    assert not any(f.rom == 0x14000 for f in sms.split(gg, tmp_path, hints={"platform": "sms"}))


@pytest.mark.parametrize("region, platform", [(6, "gg"), (4, "sms")])
def test_project_imports_pass_their_platform_to_discovery(tmp_path, region, platform):
    from decompnet.app.engine import RomNetwork

    net = RomNetwork(tmp_path / "app.db", tmp_path / "work")
    net.auto_install_tools = False
    slug = net.import_rom(_rom(region), confirmed=True, name=f"fixture.{platform}", log=lambda *_: None)
    proj = net.store.one("SELECT * FROM projects WHERE slug=?", slug)
    assert net._hints(proj)["platform"] == platform
    assert any(row["rom_offset"] == 0x14000 for row in net.store.all("SELECT * FROM functions")) is (platform == "gg")
