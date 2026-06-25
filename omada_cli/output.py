"""Tiny output helpers: aligned tables, JSON, and severity coloring."""
import json
import os
import sys

_COLOR = sys.stdout.isatty() and os.environ.get("NO_COLOR") is None
_C = {"red": "31", "yellow": "33", "green": "32", "cyan": "36", "dim": "2"}


def color(text, name):
    if not _COLOR or name not in _C:
        return text
    return f"\033[{_C[name]}m{text}\033[0m"


def emit_json(obj):
    print(json.dumps(obj, indent=2, default=str))


def table(headers, rows, aligns=None):
    """Print a left/right aligned table. rows = list of tuples of str."""
    cols = len(headers)
    rows = [[("" if c is None else str(c)) for c in r] for r in rows]
    widths = [len(h) for h in headers]
    for r in rows:
        for i in range(cols):
            widths[i] = max(widths[i], len(r[i]))
    aligns = aligns or ["<"] * cols

    def fmt(cells, dim=False):
        out = "  ".join(f"{c:{aligns[i]}{widths[i]}}" for i, c in enumerate(cells))
        return color(out, "dim") if dim else out

    print(color(fmt(headers), "cyan"))
    for r in rows:
        print(fmt(r))
