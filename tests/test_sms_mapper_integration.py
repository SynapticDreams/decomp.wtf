"""Declared models reach discovery, banked operations, judging and standalone SMS/GG rebuilding."""
from pathlib import Path

import pytest

from decompnet.app.engine import RomNetwork
from decompnet.network import NetworkError
from decompnet.rom import sms_asm
from decompnet.rom.sms_mapping import BusState

from .test_sms import make_rom

REASON = "The authored fixture declares its cartridge wiring and mapper behavior."
CODE = {0: bytes.fromhex("3e01 32ffff cd0002 18fe"), 0x200: bytes.fromhex("cd0080 c9"),
        0x4000: bytes.fromhex("3e01 c9"), 0x8000: bytes.fromhex("3e02 c9")}


@pytest.mark.parametrize("platform,region", [("sms", 4), ("gg", 6)])
@pytest.mark.parametrize("mapper,flat,value", [("sega", 0x4000, 1), ("mapperless", 0x8000, 2), ("codemasters", 0xC000, 3)])
@pytest.mark.skipif(not sms_asm.available(), reason="needs WLA-DX")
def test_declared_models_agree_across_project_consumers(tmp_path, platform, region, mapper, flat, value):
    net = RomNetwork(tmp_path / "state.db", tmp_path / "projects")
    net.auto_install_tools = False
    code = {**CODE, 0: bytes.fromhex("3e03 320080 cd0002 18fe"), 0xC000: bytes.fromhex("3e03 c9")} \
        if mapper == "codemasters" else CODE
    image = make_rom(size=0x10000 if mapper == "codemasters" else 0xC000, region=region, code=code)
    slug = net.import_rom(image, name=f"fixture.{platform}", confirmed=True, log=lambda *_: None)
    proj = net.project_row(slug)
    identity = net.cfg(proj)["rom"]["identity"]
    view = net.sms.configure(slug, mapper, "annotated-original", REASON)
    assert view["supported"] and view["discovery"] == f"declared-{mapper}-model"
    if mapper == "mapperless":
        with pytest.raises(NetworkError, match="resplit first"):
            net.sms.require(slug)
    preview = net.resplit_banked(slug, apply=False, log=lambda *_: None)
    assert preview["after"] > 0
    net.resplit_banked(slug, apply=True, log=lambda *_: None)
    net.sms.require(slug)
    proj = net.project_row(slug)
    assert net.cfg(proj)["rom"]["identity"] == identity
    assert net._hints(proj)["mapper"] == mapper
    lane = net._lane(proj)
    assert lane.sms_mapper == mapper
    assert lane.flat_of(0x8000, 0, 0, mapping=BusState.cartridge_only((0, 1, flat // 0x4000 if mapper != "mapperless" else 1))) == flat
    fn = net.store.one("SELECT * FROM functions WHERE project_id=? AND rom_offset=?", proj["id"], flat)
    assert fn is not None and fn["vram"] == 0x8000
    routine = net._routine(proj, fn)
    assert routine.mapper == mapper and routine.rom_size == len(image)
    text = ("; Returns the authored handler value without changing the mapping.\n"
            "; Input: none. Output: A contains the handler value, flags preserved.\n"
            f"MappedHandler:\n    ld a, {value}\n    ret\n")
    verdict = sms_asm.judge(routine, text)
    assert verdict.ok, verdict.problems
    with net.store.tx() as db:
        db.execute("UPDATE functions SET name='MappedHandler', status='documented', matched_source=? WHERE id=?",
                   (text, fn["id"]))
        db.execute("UPDATE symbols SET name='MappedHandler' WHERE project_id=? AND name=?", (proj["id"], fn["name"]))
    result = net.export_rom(slug, log=lambda *_: None)
    assert result["identical"] and result["documented"] == 1 and not result["left_out"]
    assert result["sms_profile"]["profile"]["mapper"] == mapper
    out = Path(result["path"])
    assert (out / "build" / f"game.{platform}").read_bytes() == image


def test_mapperless_profile_rejects_an_image_larger_than_its_address_space(tmp_path):
    net = RomNetwork(tmp_path / "state.db", tmp_path / "projects")
    net.auto_install_tools = False
    slug = net.import_rom(make_rom(size=0x20000), name="fixture.sms", confirmed=True, log=lambda *_: None)
    before = net.cfg(net.project_row(slug))
    with pytest.raises(NetworkError, match="48 KiB"):
        net.sms.configure(slug, "mapperless", "annotated-original", REASON)
    assert net.cfg(net.project_row(slug)) == before


def test_old_unsupported_mapperless_declaration_remains_readable_and_correctable(tmp_path):
    net = RomNetwork(tmp_path / "state.db", tmp_path / "projects")
    net.auto_install_tools = False
    slug = net.import_rom(make_rom(size=0x20000), name="fixture.sms", confirmed=True, log=lambda *_: None)
    net.sms.configure(slug, "sega", "annotated-original", REASON)
    net._update_cfg(slug, lambda cfg: cfg["sms_profile"].update(mapper="mapperless"))  # previously recordable as unsupported
    before = net.cfg(net.project_row(slug))
    view = net.sms.inspect(slug)
    assert not view["supported"] and view["status"] == "unsupported" and "48 KiB" in view["message"]
    assert view["profile"]["mapper"] == "mapperless" and net.cfg(net.project_row(slug)) == before
    assert net.sms.configure(slug, "sega", "annotated-original", REASON)["supported"]
    assert net.cfg(net.project_row(slug))["rom"] == before["rom"]
