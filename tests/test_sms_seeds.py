"""Seed adapters use declared hardware/coordinates rather than fixed-slot display assumptions."""
from decompnet.rom import coverage, sms, sms_seeds, sms_trace
from decompnet.rom.sms_mapping import Mapper

from .test_sms import make_rom


def test_unqualified_sega_call_scan_only_resolves_fixed_prefix_targets():
    image = make_rom(size=0x20000, code={0x100: bytes.fromhex("cd3412 cd3402"),
                                        0x234: bytes.fromhex("3e01c9"), 0x1234: bytes.fromhex("3e02c9")})
    targets = list(sms_seeds.call_targets(image, 0, Mapper("sega", len(image))))
    assert (0x234, 0x234) in targets and (0x1234, 0x1234) not in targets


def test_mapperless_call_scan_has_flat_wiring_without_reset_bank_facts():
    image = make_rom(size=0xC000, code={0x100: bytes.fromhex("cd3481")})
    assert (0x8134, 0x8134) in sms_seeds.call_targets(image, 0, Mapper("mapperless", len(image)))


def test_symbol_coordinates_allow_paged_slot_zero_and_reject_impossible_prefixes_and_ram():
    model = Mapper("sega", 0x20000)
    labels = {(4, 0x1234): "Paged", (4, 0x123): "WrongPrefix", (0, 0xC100): "WorkRam"}
    assert list(sms_seeds.symbol_targets(labels, model)) == [(0x11234, 0x1234)]


def test_declared_table_cpu_window_keeps_paged_slot_zero_targets_distinct():
    image = make_rom(size=0x20000, code={0x11000: bytes.fromhex("0012")})
    model = Mapper("sega", len(image))
    assert list(sms_seeds.table_targets(image, [(0x11000, 1)], {0x11000: 0x1000}, model)) == [(0x11200, 0x1200)]
    assert not list(sms_seeds.table_targets(image, [(0x11000, 1)], {}, model))


def test_mapperless_symbols_must_match_the_flat_physical_coordinate():
    model = Mapper("mapperless", 0xC000)
    assert list(sms_seeds.symbol_targets({(2, 0x8123): "Flat", (1, 0x8123): "Wrong"}, model)) == [(0x8123, 0x8123)]


def test_trace_symbol_adapter_preserves_slot_zero_mapping():
    image = make_rom(size=0x20000, code={0x11234: bytes.fromhex("3e04c9")})
    assert sms_trace.sym_seeds({(4, 0x1234): "Paged"}, image) == {0x11234: (0x1234, "sym")}


def test_physical_cdl_entries_do_not_invent_a_sega_cpu_window():
    image = make_rom(size=0xC000, code={0: bytes.fromhex("18fe"), 0x700: bytes.fromhex("3e03c9"),
                                      **{at: b"\xc9" for at in sms.VECTORS if at}})
    flags = bytearray(len(image))
    flags[0x700:0x703] = b"\x09\x01\x01"
    cov = coverage.read_cdl(bytes(flags), image)
    assert cov.entries == {0x700}  # retained physical evidence
    assert 0x700 not in sms.candidates(image, hints={"coverage": cov})[0]
    assert sms.candidates(image, hints={"coverage": cov}, mapper="mapperless")[0][0x700] == (0x700, "ran")
    assert sms.candidates(image, labels={(0, 0x700): "_LABEL_700_"}, hints={"coverage": cov})[0][0x700][0] == 0x700
