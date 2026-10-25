#!/usr/bin/env python3
"""Compare per-plane compressed block sizes: oracle vs native, for one fixture.

Block sizes are a decoder-free proxy for how much ink a plane carries, so a
large difference localises which plane's separation is wrong without needing
a validated 10-/12-bit decoder.
"""
from __future__ import annotations

import io
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))
sys.path.insert(0, str(HERE.parent / "hl3040cn" / "src"))

import band  # noqa: E402
import pclxl  # noqa: E402
import pipeline  # noqa: E402
from ppm import read_ppm  # noqa: E402
from settings import PrintSettings  # noqa: E402

FIX = Path("/mnt/ssd/bprobe")


def oracle_sizes(name: str) -> dict[str, list[int]]:
    """Per-plane block sizes (sum of data bytes) from the oracle fixture."""
    ops = pclxl.parse((FIX / f"{name}.xl2hb").read_bytes())
    out: dict[str, list[int]] = defaultdict(list)
    for blk in band.decode_blocks(ops):
        out[blk.plane_name].append(blk.header.data_size)
    return out


def native_sizes(name: str, table=None) -> dict[str, list[int]]:
    """Per-plane block sizes from the native pipeline."""
    w, h, _mx, px = read_ppm(io.BytesIO((FIX / f"{name}.ppm").read_bytes()))
    s = PrintSettings()
    s.page_size = "Letter"
    orig = pipeline.color_table
    if table is not None:
        pipeline.color_table = lambda _s: table
    try:
        buf = io.BytesIO()
        pipeline.filter_page(w, h, px, s, buf)
    finally:
        pipeline.color_table = orig
    ops = pclxl.parse(buf.getvalue())
    out: dict[str, list[int]] = defaultdict(list)
    for blk in band.decode_blocks(ops):
        out[blk.plane_name].append(blk.header.data_size)
    return out


def main() -> int:
    """Print the per-plane size comparison for each fixture given."""
    from color_lut import ColorTable

    for name in sys.argv[1:] or ["red"]:
        o = oracle_sizes(name)
        print(f"=== {name} ===")
        print(f"{'Tabelle':22s} | " + " | ".join(f"{p:>18s}" for p in ("K", "C", "M", "Y")))
        print(f"{'ORACLE':22s} | " + " | ".join(f"{sum(o.get(p,[])):18d}" for p in ("K", "C", "M", "Y")))
        for label, tbl in (
            ("rgb_default", ColorTable("rgb")),
            ("rgb_ig_default", ColorTable("rgb", improve_gray=True)),
            ("srgb_default", ColorTable("srgb")),
            ("cmyk_default", ColorTable("cmyk")),
        ):
            n = native_sizes(name, tbl)
            print(f"{label:22s} | " + " | ".join(f"{sum(n.get(p,[])):18d}" for p in ("K", "C", "M", "Y")))
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
