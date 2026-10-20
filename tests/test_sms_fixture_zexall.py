"""A real program with published source, end to end (tools/sms_fixtures.py): zexall-sms, built at a pinned commit with
the pinned WLA-DX, imported, declared, split and exported. Its own symbol file is the ground truth: every routine its
source calls must be found where it starts, discovery must stay within its budgets, and the export must rebuild the
image byte for byte. Nothing of the program is kept in this repository."""

from __future__ import annotations

from pathlib import Path
import re
import sys

import pytest

from decompnet import toolchains
from decompnet.app.engine import RomNetwork
from decompnet.rom import sms_asm

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import sms_fixtures  # noqa: E402

pytestmark = pytest.mark.skipif(not sms_asm.available(), reason="needs WLA-DX")


def physical(sym: str) -> dict[str, int]:
    """name -> ROM offset for the symbol file's ROM labels (16 KiB banks, as the fixture's memory map has them)."""
    out = {}
    for line in sym.split("[labels]", 1)[1].splitlines():
        if (m := re.match(r"^([0-9a-f]{2}):([0-9a-f]{4}) (\S+)$", line.strip())) and int(m.group(2), 16) < 0xC000:
            out.setdefault(m.group(3), int(m.group(1), 16) * 0x4000 + (int(m.group(2), 16) & 0x3FFF))
    return out


def test_zexall_rebuilds_and_every_routine_its_source_calls_is_found(tmp_path):
    source = sms_fixtures.fetch("zexall-sms", toolchains.root() / ".fixtures")
    image, sym = sms_fixtures.build_zexall(source, tmp_path, sms_asm._tools())
    labels = physical(sym)
    called = sms_fixtures.called_labels((source / "source" / "zexall.sms.asm").read_text(encoding="latin-1"))
    in_ram = called - set(labels)  # (code it copies to RAM first: RAM execution is outside static discovery)
    assert in_ram <= set(re.findall(r"^[0-9a-f]{2}:[c-f][0-9a-f]{3} (\S+)$", sym, re.M))
    called -= in_ram
    assert len(called) >= 30

    net = RomNetwork(tmp_path / "state.db", tmp_path / "projects")
    net.auto_install_tools = False
    slug = net.import_rom(image, name="zexall.sms", confirmed=True, log=lambda *_: None)
    net.sms.configure(slug, "sega", "annotated-original",
                      "Built from the pinned zexall-sms source; its memory map pages 64 KiB through the Sega mapper.")
    result = net.resplit_banked(slug, apply=True, log=lambda *_: None)
    assert result["analysis_limits"]["exhausted"] == []
    pid = net.project_row(slug)["id"]
    starts = {row["rom_offset"] for row in net.store.all("SELECT rom_offset FROM functions WHERE project_id=?", pid)}
    assert sorted(name for name in called if labels[name] not in starts) == []

    exported = net.export_rom(slug, log=lambda *_: None)
    assert exported["identical"], exported["log"]
