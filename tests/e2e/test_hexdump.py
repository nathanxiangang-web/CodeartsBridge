# AI生成
"""Tests for bridge.hexdump helper."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from bridge.hexdump import hexdump


class TestHexdumpBasic:
    def test_empty_returns_empty_string(self):
        assert hexdump(b"") == ""

    def test_single_byte(self):
        assert hexdump(b"A") == (
            "00000000  41                                                |A|\n"
            "00000001"
        )

    def test_hello(self):
        assert hexdump(b"Hello") == (
            "00000000  48 65 6c 6c 6f                                    |Hello|\n"
            "00000005"
        )

    def test_trailing_offset_is_total_length(self):
        out = hexdump(b"abc")
        assert out.endswith("00000003")


class TestHexdumpFullLine:
    def test_exactly_16_bytes_no_padding_in_hex(self):
        data = b"0123456789abcdef"
        out = hexdump(data)
        lines = out.split("\n")
        assert len(lines) == 2
        assert lines[0] == (
            "00000000  30 31 32 33 34 35 36 37  38 39 61 62 63 64 65 66  |0123456789abcdef|"
        )
        assert lines[1] == "00000010"

    def test_multiple_lines(self):
        data = bytes(range(20))
        out = hexdump(data)
        lines = out.split("\n")
        assert len(lines) == 3
        assert lines[0].startswith("00000000")
        assert lines[1].startswith("00000010")
        assert lines[2] == "00000014"


class TestHexdumpAscii:
    def test_non_printable_shown_as_dots(self):
        out = hexdump(b"\x00\x01\x02")
        assert "|...|" in out

    def test_high_bytes_as_dots(self):
        out = hexdump(b"\xff\xfe")
        assert "|..|" in out

    def test_mixed_printable_and_non_printable(self):
        out = hexdump(b"A\x00B")
        assert "|A.B|" in out

    def test_printable_range_inclusive(self):
        out = hexdump(bytes([32, 126]))
        assert "| ~|" in out


class TestHexdumpWidth:
    def test_custom_width_8(self):
        data = b"01234567"
        out = hexdump(data, width=8)
        lines = out.split("\n")
        assert lines[0] == "00000000  30 31 32 33  34 35 36 37  |01234567|"
        assert lines[1] == "00000008"

    def test_custom_width_4_multiple_lines(self):
        data = b"01234567"
        out = hexdump(data, width=4)
        lines = out.split("\n")
        assert len(lines) == 3
        assert lines[0] == "00000000  30 31  32 33  |0123|"
        assert lines[1] == "00000004  34 35  36 37  |4567|"
        assert lines[2] == "00000008"

    def test_width_1(self):
        out = hexdump(b"AB", width=1)
        lines = out.split("\n")
        assert lines[0] == "00000000  41  |A|"
        assert lines[1] == "00000001  42  |B|"
        assert lines[2] == "00000002"

    def test_partial_line_padded_to_full_width(self):
        out = hexdump(b"AB", width=8)
        line = out.split("\n")[0]
        hex_section = line[10:34]
        assert hex_section == "41 42" + " " * 19


class TestHexdumpValidation:
    def test_width_zero_raises(self):
        with pytest.raises(ValueError):
            hexdump(b"x", width=0)

    def test_width_negative_raises(self):
        with pytest.raises(ValueError):
            hexdump(b"x", width=-4)

    def test_accepts_bytes(self):
        assert hexdump(bytes([65])) == (
            "00000000  41                                                |A|\n"
            "00000001"
        )

    def test_accepts_bytearray(self):
        out = hexdump(bytearray(b"AB"))
        assert "|AB|" in out
