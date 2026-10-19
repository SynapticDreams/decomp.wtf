"""Research locations preserve explicit physical coordinates and do not invent live slot selections."""
import pytest

from decompnet.rom import sms_locations
from decompnet.rom.sms_mapping import Mapper


def test_sega_explicit_coordinates_allow_paged_slot_zero_and_bank_zero_in_other_windows():
    model = Mapper("sega", 0x20000)
    assert sms_locations.resolve(model, "04:1234") == (0x11234, 0x1234)
    assert sms_locations.resolve(model, "00:8123") == (0x123, 0x8123)
    for text in ("04:0123", "05:c123", "09:8123"):
        with pytest.raises(ValueError, match="isn't in the ROM"):
            sms_locations.resolve(model, text)


def test_unqualified_addresses_need_evidence_for_their_own_window():
    model = Mapper("sega", 0x20000)
    assert sms_locations.resolve(model, "$0123") == (0x123, 0x123)
    assert sms_locations.resolve(model, "8123", (0x14000, 0x8000)) == (0x14123, 0x8123)
    for text, context in (("1234", None), ("8123", None), ("4123", (0x14000, 0x8000))):
        with pytest.raises(ValueError, match="explicit NN:AAAA"):
            sms_locations.resolve(model, text, context)


def test_mapperless_locations_follow_flat_wiring_and_validate_contexts():
    model = Mapper("mapperless", 0xC000)
    assert sms_locations.resolve(model, "8123") == (0x8123, 0x8123)
    assert sms_locations.resolve(model, "02:8123") == (0x8123, 0x8123)
    with pytest.raises(ValueError, match="isn't in the ROM"):
        sms_locations.resolve(model, "01:8123")
    with pytest.raises(ValueError, match="function's CPU/physical"):
        sms_locations.coordinate(model, 0x4123, 0x8123)
