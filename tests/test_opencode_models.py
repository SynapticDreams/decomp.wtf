"""The model picker offers free OpenCode models and a small Go selection from the user's CLI catalog."""

import json
import subprocess

from decompnet.app import agents


def catalog(*rows):
    return "\n".join(model + "\n" + json.dumps(info, indent=2) for model, info in rows)


def priced(name, input_cost=0, output_cost=0):
    return {"name": name, "cost": {"input": input_cost, "output": output_cost}}


def test_signed_out_catalog_keeps_free_models_without_inventing_go_access():
    output = catalog(
        ("opencode/big-pickle", priced("Big Pickle")),
        ("opencode/new-preview", priced("New Preview")),  # price, not its name, says it is free
        ("opencode/output-only", priced("Output Only", output_cost=1)),
        ("opencode/paid-free", priced("Paid Despite Name", input_cost=1)),
    )
    models = agents._opencode_models(output)
    assert [m["id"] for m in models] == ["opencode/big-pickle", "opencode/new-preview"]
    assert models[1] == {"id": "opencode/new-preview", "name": "New Preview", "note": "OpenCode · free"}


def test_signed_in_catalog_adds_only_budget_go_models_and_freebies():
    output = catalog(
        ("opencode/big-pickle", priced("Big Pickle")),
        ("opencode/deepseek-v4.1-flash", priced("DeepSeek V4.1 Flash", .15, .6)),
        ("opencode-go/beam-free", priced("Beam Free")),
        ("opencode-go/kimi-k3", priced("Kimi K3", 3, 15)),
        ("opencode-go/qwen3.7-plus", priced("Qwen3.7 Plus", .4, 1.6)),
        ("opencode-go/glm-5.3-flash", priced("GLM-5.3-Flash", .15, .5)),
        ("opencode-go/mimo-v2.6-flash", priced("MiMo-V2.6-Flash", .14, .28)),
        ("opencode-go/deepseek-v4.1-flash", priced("DeepSeek V4.1 Flash", .15, .6)),
        ("opencode-go/longcat-2.5-preview-free", priced("LongCat 2.5 Preview Free")),
        ("opencode-go/new-free-offer", priced("New Free Offer")),
        ("openrouter/user-model", priced("User Model", 2, 8)),
    )
    models = agents._opencode_models(output)
    assert [m["id"] for m in models] == [
        "opencode-go/deepseek-v4.1-flash", "opencode-go/mimo-v2.6-flash",
        "opencode-go/glm-5.3-flash", "opencode-go/qwen3.7-plus",
        "opencode/big-pickle", "opencode-go/beam-free", "opencode-go/longcat-2.5-preview-free",
        "opencode-go/new-free-offer", "openrouter/user-model",
    ]
    assert models[0] == {"id": "opencode-go/deepseek-v4.1-flash", "name": "DeepSeek V4.1 Flash",
                         "note": "OpenCode Go · value pick"}
    assert models[5]["note"] == "OpenCode Go · free"
    assert models[-1]["note"] == "openrouter"


def test_plain_or_damaged_metadata_has_a_conservative_fallback():
    output = ("Loading catalog\n"
              "opencode/big-pickle\n"
              "opencode/paid-model\n"
              "opencode/old-free\n{invalid JSON\n"
              "opencode-go/mimo-v2.6-flash\n"
              "opencode-go/expensive\n"
              "opencode-go/beam-free\n[]\n"
              "custom/local-model\n")
    models = agents._opencode_models(output)
    assert [m["id"] for m in models] == [
        "opencode-go/mimo-v2.6-flash", "opencode/big-pickle", "opencode/old-free",
        "opencode-go/beam-free", "custom/local-model",
    ]
    assert models[0]["name"] == "mimo-v2.6-flash"


def test_go_selection_is_not_lost_behind_a_large_paid_catalog():
    output = catalog(*[(f"opencode/paid-{i}", priced("Paid", 1, 2)) for i in range(220)],
                     ("opencode-go/mimo-v2.6-flash", priced("MiMo-V2.6-Flash", .14, .28)))
    assert [m["id"] for m in agents._opencode_models(output)] == ["opencode-go/mimo-v2.6-flash"]


def test_cli_discovery_refreshes_after_sign_in_and_sign_out(monkeypatch):
    monkeypatch.setattr(agents, "_models", {})
    now = [1000]
    monkeypatch.setattr(agents.time, "time", lambda: now[0])
    free = catalog(("opencode/big-pickle", priced("Big Pickle")))
    current = [free]
    calls = []

    def run(cmd, **kwargs):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, current[0])

    monkeypatch.setattr(agents.subprocess, "run", run)
    assert [m["id"] for m in agents.models("opencode", "opencode")] == ["opencode/big-pickle"]
    current[0] += "\n" + catalog(("opencode-go/mimo-v2.6-flash", priced("MiMo-V2.6-Flash", .14, .28)))
    assert len(agents.models("opencode", "opencode")) == 1  # the normal short-lived cache
    now[0] += 61
    assert agents.models("opencode", "opencode")[0]["id"] == "opencode-go/mimo-v2.6-flash"
    current[0] = free
    now[0] += 61
    assert [m["id"] for m in agents.models("opencode", "opencode")] == ["opencode/big-pickle"]
    assert calls == [["opencode", "models", "--verbose"]] * 3
