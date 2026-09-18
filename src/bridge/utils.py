# AI生成
"""General-purpose utility helpers for CodeartsBridge."""

from __future__ import annotations


def format_duration(seconds: float) -> str:
    """Format a duration in seconds into a compact human-readable string.

    The output uses the largest units available.  Once a larger unit
    appears, every smaller unit is also shown so the layout stays
    consistent.  Sub-second fractions are preserved on the seconds
    component only.

    Examples:
        0.5  -> "0.5s"
        90   -> "1m30s"
        3700 -> "1h1m40s"
    """
    if seconds < 0:
        raise ValueError("seconds must be non-negative")

    total = float(seconds)
    hours = int(total // 3600)
    total -= hours * 3600
    minutes = int(total // 60)
    secs = total - minutes * 60

    if secs == int(secs):
        secs_str = str(int(secs))
    else:
        secs_str = repr(secs)

    parts: list[str] = []
    if hours > 0:
        parts.append(f"{hours}h")
        parts.append(f"{minutes}m")
    elif minutes > 0:
        parts.append(f"{minutes}m")
    parts.append(f"{secs_str}s")
    return "".join(parts)
