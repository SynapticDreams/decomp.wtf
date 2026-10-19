"""The frontend can launch assembly helpers for every supported CPU, without running an agent or assembler."""

import json

import pytest
from starlette.testclient import TestClient

from decompnet.app import agents
from decompnet.app.engine import RomNetwork
from decompnet.app.server import build


@pytest.fixture
def launcher(tmp_path, monkeypatch):
    net = RomNetwork(tmp_path / "app.db", tmp_path)
    mcp, manager, security = build(net, tmp_path / ".decomp", 6497, "k")
    monkeypatch.setattr(agents.Manager, "_run", lambda self, session: None)
    client = TestClient(mcp.streamable_http_app(transport_security=security, host="127.0.0.1"),
                        base_url="http://127.0.0.1:6497")
    client.cookies.set("decomp_live", "k")

    def project(platform, arch, *, kind="rom", status="asm", reason="hand-written routine"):
        cfg = {"kind": kind, "platform": platform, "arch": arch, "rom": {"size": 0x8000}}
        with net.store.tx() as db:
            pid = db.execute("INSERT INTO projects(slug,name,arch,root,config) VALUES(?,?,?,?,?)",
                             ("fixture", "fixture", arch, str(tmp_path), json.dumps(cfg))).lastrowid
            db.execute("INSERT INTO functions(project_id,name,size,n_insns,status,meta) VALUES(?,?,?,?,?,?)",
                       (pid, "Routine", 1, 1, status, json.dumps({"asm_code": reason})))

    return net, manager, client, project


def start(client):
    return client.post("/api/agents/start", headers={"X-Decomp": "1"},
                       json={"kind": "claude", "slug": "fixture", "options": {"track": "asm"}})


@pytest.mark.parametrize("platform,arch", [
    ("gb", "sm83"), ("gbc", "sm83"), ("sms", "z80"), ("gg", "z80"), ("nes", "mos6502"),
])
def test_supported_platforms_launch_with_assembly_work_and_no_c_candidates(launcher, platform, arch):
    _, manager, client, project = launcher
    project(platform, arch)
    assert manager._left("fixture") == 0
    response = start(client)
    assert response.status_code == 200, response.text
    (sid,) = response.json()["started"]
    session = manager.sessions[sid]
    assert session.options["track"] == "asm" and session.snapshot()["track"] == "asm"
    assert manager._left("fixture", "asm") == 1


@pytest.mark.parametrize("platform,arch,kind", [
    ("n64", "mips", "rom"), ("gba", "arm", "rom"), ("sms", "", "rom"),
    ("gb", "sm83", "fork"), ("sms", "z80", "fork"), ("nes", "mos6502", "fork"),
])
def test_unsupported_architectures_and_forks_cannot_launch(launcher, platform, arch, kind):
    _, manager, client, project = launcher
    project(platform, arch, kind=kind)
    response = start(client)
    assert response.status_code == 400, response.text
    assert "the assembly track is for Game Boy, Master System, Game Gear and NES projects" in response.json()["error"]
    assert not manager.sessions


@pytest.mark.parametrize("status,reason", [
    ("open", "hand-written routine"), ("documented", "hand-written routine"),
    ("asm", "padding (00 or FF bytes only), not a function"),
])
def test_projects_without_eligible_assembly_work_cannot_launch(launcher, status, reason):
    _, manager, client, project = launcher
    project("sms", "z80", status=status, reason=reason)
    response = start(client)
    assert response.status_code == 400, response.text
    assert "Nothing to start on" in response.json()["error"]
    assert not manager.sessions
