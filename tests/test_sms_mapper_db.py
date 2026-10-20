"""Software-list catalog evidence (rom/sms_mapper_db.py, tools/sms_softlist.py): a known dump's MAME board record is
shown beside the byte-pattern suggestions, never declares a model, and the bundled extract keeps only hashes and
board features from CC0 lists."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

import pytest

from decompnet.app.engine import RomNetwork
from decompnet.rom import sms_mapper_db, sms_mapper_evidence

from .test_sms import make_rom


def test_the_bundled_catalog_is_cc0_hashes_and_board_features_only():
    data = json.loads(sms_mapper_db.DB.read_text(encoding="utf-8"))
    assert data["format"] == 1 and data["license"] == "CC0-1.0"
    assert set(data["list_sha256"]) == {"sms", "gamegear"}
    assert len(data["records"]) > 1000
    for sha1, listed, slot, flags in data["records"]:
        assert re.fullmatch(r"[0-9a-f]{40}", sha1) and listed in ("sms", "gamegear")
        assert re.fullmatch(r"[a-z0-9_]*", slot) and set(flags) <= {"sms_mode", "battery"}
    boards = {slot for _sha1, _list, slot, _flags in data["records"]}
    assert {"", "codemasters", "korean", "4pak", "janggun", "eeprom"} <= boards


@pytest.fixture
def catalog(monkeypatch):
    records = {}
    monkeypatch.setattr(sms_mapper_db, "_records", lambda: records)
    return records


def test_a_known_dump_names_its_board_and_the_models_that_cover_it(catalog):
    small, large = make_rom(size=0x8000), make_rom(size=0x40000)
    catalog[hashlib.sha1(small).hexdigest()] = [("sms", "", ())]
    catalog[hashlib.sha1(large).hexdigest()] = [("gamegear", "codemasters", ("battery",)),
                                                 ("gamegear", "eeprom", ("sms_mode",))]
    assert sms_mapper_db.lookup(small)["matches"] == [
        {"list": "sms", "board": "default", "models": ["sega", "mapperless"], "sms_mode": False, "battery": False}]
    found = sms_mapper_db.lookup(large)
    assert found["available"] and found["sha1"] == hashlib.sha1(large).hexdigest()
    assert found["matches"] == [
        {"list": "gamegear", "board": "codemasters", "models": ["codemasters"], "sms_mode": False, "battery": True},
        {"list": "gamegear", "board": "eeprom", "models": ["unsupported"], "sms_mode": True, "battery": False}]
    assert "doesn't establish the wiring" in found["message"]
    assert found["source"]["license"] == "CC0-1.0"


def test_an_unknown_image_has_no_match_and_proves_nothing(catalog):
    found = sms_mapper_db.lookup(make_rom())
    assert found["available"] and found["matches"] == [] and "says nothing" in found["message"]


def test_an_unreadable_catalog_is_unavailable_not_an_error(monkeypatch, tmp_path):
    monkeypatch.setattr(sms_mapper_db, "_records", lambda: (_ for _ in ()).throw(ValueError("bad")))
    assert sms_mapper_db.lookup(make_rom()) == {
        "available": False, "matches": [], "message": "The bundled software-list catalog is unavailable."}


def test_catalog_evidence_stays_separate_from_byte_pattern_candidates(catalog):
    image = make_rom(size=0x20000, code={0: bytes.fromhex("32ffff")})
    catalog[hashlib.sha1(image).hexdigest()] = [("sms", "codemasters", ())]
    report = sms_mapper_evidence.inspect(image)
    assert report["candidates"] == [{"mapper": "sega", "confidence": "low"}]
    assert report["catalog"]["matches"][0]["models"] == ["codemasters"] and report["requires_declaration"]


def test_project_inspection_shows_the_catalog_without_declaring_a_model(tmp_path, catalog):
    image = make_rom(code={0: bytes.fromhex("18fe")})
    catalog[hashlib.sha1(image).hexdigest()] = [("sms", "codemasters", ())]
    net = RomNetwork(tmp_path / "state.db", tmp_path / "projects")
    net.auto_install_tools = False
    slug = net.import_rom(image, name="fixture.sms", confirmed=True, log=lambda *_: None)
    before = net.cfg(net.project_row(slug))
    report = net.sms.inspect(slug)
    assert report["suggestions"]["catalog"]["matches"][0]["board"] == "codemasters"
    assert report["profile"]["mapper"] == "unknown" and net.cfg(net.project_row(slug)) == before


LIST = """<?xml version="1.0" encoding="UTF-8"?>
<!--
license:CC0-1.0
-->
<softwarelist name="{name}" description="test">
  <software name="one"><description>A Title</description><publisher>Someone</publisher>
    <part name="cart" interface="x"><feature name="slot" value="codemasters" /><feature name="battery" value="yes" />
      <dataarea name="rom" size="32768"><rom name="a.bin" size="32768" crc="00000000" sha1="{one}" /></dataarea></part>
  </software>
  <software name="two"><description>B Title</description>
    <part name="cart" interface="x"><feature name="pin_42" value="sms_mode" />
      <dataarea name="rom" size="32768"><rom name="b.bin" size="32768" crc="00000000" sha1="{two}" /></dataarea></part>
  </software>
  <software name="split"><description>C Title</description>
    <part name="cart" interface="x"><dataarea name="rom" size="65536">
      <rom name="c1.bin" size="32768" crc="00000000" sha1="{one}" />
      <rom name="c2.bin" size="32768" crc="00000000" sha1="{two}" /></dataarea></part>
  </software>
</softwarelist>
"""


def test_the_extractor_keeps_single_image_hashes_and_features_without_titles(tmp_path, monkeypatch):
    from tools import sms_softlist

    one, two = "1" * 40, "2" * 40
    (tmp_path / "sms.xml").write_text(LIST.format(name="sms", one=one, two=two), encoding="utf-8")
    (tmp_path / "gamegear.xml").write_text(LIST.format(name="gamegear", one=one, two=two), encoding="utf-8")
    out = tmp_path / "softlist.json"
    monkeypatch.setattr(sms_softlist, "OUT", out)
    monkeypatch.setattr(sms_softlist, "ROOT", tmp_path)
    monkeypatch.setattr(sys, "argv", ["sms_softlist.py", str(tmp_path / "sms.xml"), str(tmp_path / "gamegear.xml")])
    assert sms_softlist.main() == 0
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["records"] == [[one, "gamegear", "codemasters", ["battery"]], [one, "sms", "codemasters", ["battery"]],
                               [two, "gamegear", "", ["sms_mode"]], [two, "sms", "", ["sms_mode"]]]
    assert "Title" not in out.read_text(encoding="utf-8") and "Someone" not in out.read_text(encoding="utf-8")


def test_the_extractor_refuses_a_list_without_its_cc0_notice(tmp_path):
    path = tmp_path / "sms.xml"
    path.write_text(LIST.format(name="sms", one="1" * 40, two="2" * 40).replace("license:CC0-1.0", ""),
                    encoding="utf-8")
    tool = Path(__file__).resolve().parents[1] / "tools" / "sms_softlist.py"
    run = subprocess.run([sys.executable, str(tool), str(path)], capture_output=True, text=True)
    assert run.returncode != 0 and "CC0-1.0" in run.stderr
