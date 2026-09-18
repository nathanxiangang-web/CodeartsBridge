# AI生成
"""Canonical hex dump helper for CodeartsBridge."""

from __future__ import annotations


def hexdump(data: bytes, width: int = 16) -> str:
    """Render bytes as a canonical hex dump string.

    Each line shows the byte offset, the hex values grouped in two
    halves, and the ASCII representation.  Non-printable bytes are
    shown as dots.  The output ends with a trailing offset line when
    data is non-empty, and is empty for empty input.

    Example:
        hexdump(b"Hello") ->
        00000000  48 65 6c 6c 6f                                    |Hello|
        00000005
    """
    if width <= 0:
        raise ValueError("width must be positive")

    if not data:
        return ""

    lines: list[str] = []
    for offset in range(0, len(data), width):
        chunk = data[offset:offset + width]
        lines.append(
            f"{offset:08x}  {_format_hex_line(chunk, width)}  |{_format_ascii(chunk)}|"
        )
    lines.append(f"{len(data):08x}")
    return "\n".join(lines)


def _format_hex_line(chunk: bytes, width: int) -> str:
    """Format one row of hex cells, padding short rows to width."""
    cells: list[str] = []
    for i in range(width):
        if i < len(chunk):
            cells.append(f"{chunk[i]:02x}")
        else:
            cells.append("  ")
    half = width // 2
    if width >= 2 and width % 2 == 0:
        return " ".join(cells[:half]) + "  " + " ".join(cells[half:])
    return " ".join(cells)


def _format_ascii(chunk: bytes) -> str:
    """Render printable bytes as-is, others as dots."""
    return "".join(chr(b) if 32 <= b <= 126 else "." for b in chunk)
