"""Revision and declaration checks around banked discovery and database mutation."""
from pathlib import Path
import re

from ..network import NetworkError
from ..rom import sms_identity


def verify_input(arch: str, path: Path, cfg: dict) -> None:
    if arch != "z80":
        return
    try:
        identity, legacy = cfg["rom"].get("identity"), cfg["rom"].get("sha1")
        if identity is not None and not isinstance(identity, dict):
            raise ValueError("invalid frozen ROM identity")
        if identity is None and (not isinstance(legacy, str) or not re.fullmatch(r"[0-9a-f]{40}", legacy)):
            raise ValueError("frozen ROM identity is unavailable; declare a profile to bind this revision")
        image = sms_identity.strip_copier_header(path.read_bytes())
        sms_identity.verify_normalized(image, identity, legacy)
    except (OSError, ValueError, TypeError) as exc:
        # File errors can contain local paths; the operator needs the remedy, not that path.
        reason = "original input is unavailable" if isinstance(exc, OSError) else str(exc)
        raise NetworkError(f"cannot resplit SMS/GG input: {reason}") from None


def verify_settings(expected: dict, current: dict) -> None:
    if any(expected.get(key) != current.get(key) for key in ("rom", "sms_profile")):
        raise NetworkError("mapping or ROM metadata changed during resplit; retry with the current declaration")
    if expected != current:
        raise NetworkError("project settings changed during resplit; retry with the current settings")


def quiet(net, slug: str) -> None:
    ap, job = net.autopilots.get(slug), net.twins.jobs.get(slug)
    pid = net._project(slug)["id"]
    if (ap and ap.get("state") == "running") or (net.permuter.status(slug) or {}).get("state") == "running" or \
            (job and job.state == "running") or pid in net.twins._busy:
        raise NetworkError("stop this project's background analysis before resplitting or undoing a resplit")
