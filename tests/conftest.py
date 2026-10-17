import os

# the apps the tests start never look for updates on the network (tests/test_updates.py checks that part offline)
os.environ.setdefault("DECOMP_UPDATES", "off")


import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _no_surprise_downloads(monkeypatch):
    """Importing a Game Boy or Master System ROM installs the free tools it needs when they are missing: a test must
    never reach for the network. (A test of that step turns it back on and fakes the installer.)"""
    from decompnet.app.engine import RomNetwork

    monkeypatch.setattr(RomNetwork, "auto_install_tools", False)
