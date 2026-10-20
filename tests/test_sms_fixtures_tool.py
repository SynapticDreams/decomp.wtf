"""The fixture helper's own conversions (tools/sms_fixtures.py), without fetching anything."""

from __future__ import annotations

from pathlib import Path
import struct
import sys
import zlib

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import sms_fixtures  # noqa: E402


def png(rows: list[bytes], width: int, filters: list[int]) -> bytes:
    def chunk(kind: bytes, body: bytes) -> bytes:
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))
    raw = b"".join(bytes([kind]) + row for kind, row in zip(filters, rows))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, len(rows), 1, 3, 0, 0, 0)) +
            chunk(b"PLTE", b"\x00\x00\x00\xff\xff\xff") + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def test_a_one_bit_png_becomes_8x8_tiles_left_to_right_then_down():
    rows = [bytes([y, 0x80 | y]) for y in range(16)]  # two tiles across, two down
    tiles = sms_fixtures.one_bpp(png(rows, 16, [0] * 16))
    assert tiles == bytes(range(8)) + bytes(0x80 | y for y in range(8)) + bytes(range(8, 16)) + \
        bytes(0x80 | y for y in range(8, 16))


@pytest.mark.parametrize("kind", [1, 2, 3, 4])
def test_png_row_filters_are_undone(kind):
    rows = [bytes([0x11 * (y + 1) & 255, 0x37 + y]) for y in range(8)]

    def filtered(y: int) -> bytes:
        prev = rows[y - 1] if y else bytes(2)
        out = bytearray()
        for x in range(2):
            left, up, corner = rows[y][x - 1] if x else 0, prev[x], prev[x - 1] if x else 0
            predictor = {1: left, 2: up, 3: (left + up) // 2}.get(kind)
            if predictor is None:
                p = left + up - corner
                pa, pb, pc = abs(p - left), abs(p - up), abs(p - corner)
                predictor = left if pa <= pb and pa <= pc else up if pb <= pc else corner
            out.append((rows[y][x] - predictor) & 255)
        return bytes(out)

    tiles = sms_fixtures.one_bpp(png([filtered(y) for y in range(8)], 16, [kind] * 8))
    assert tiles == bytes(row[0] for row in rows) + bytes(row[1] for row in rows)


def test_other_pngs_are_refused():
    with pytest.raises(ValueError, match="1-bit indexed"):
        sms_fixtures.one_bpp(png([bytes(1)] * 8, 8, [0] * 8).replace(b"\x01\x03\x00\x00\x00", b"\x08\x03\x00\x00\x00"))


def test_called_labels_are_the_routines_the_source_calls():
    source = "Start:\n  call Init\n  call nz, Print ; text\n-: call Loop\n  ld a, (call)\n  ; call Commented\n  jp Other\n"
    assert sms_fixtures.called_labels(source) == {"Init", "Print", "Loop"}
