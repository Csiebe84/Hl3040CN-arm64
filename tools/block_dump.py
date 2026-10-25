#!/usr/bin/env python3
"""Dump the raster block structure of an XL2HB stream, one line per block.

Shows the plane id (CommentData), bit width (comp_size), block height,
start line and payload size, which is what separates a band-splitting defect
from a plane-separation defect.
"""
from __future__ import annotations

import io
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))
sys.path.insert(0, str(HERE.parent / "hl3040cn" / "src"))

import band  # noqa: E402
import pclxl  # noqa: E402

FIX = Path("/mnt/ssd/bprobe")


def dump(label: str, blob: bytes, limit: int) -> None:
    """Print the block table for one stream."""
    ops = pclxl.parse(blob)
    blocks = band.decode_blocks(ops)
    print(f"--- {label}: {len(blocks)} Bloecke ---")
    print(f"{'#':>3s} {'ebene':>6s} {'cs':>3s} {'bd':>3s} {'start':>6s} {'hoehe':>6s} {'bytes':>7s}")
    for i, b in enumerate(blocks):
        if i >= limit:
            print(f"    ... ({len(blocks) - limit} weitere)")
            break
        h = b.header
        print(
            f"{i:3d} {b.plane_name:>6s} {h.comp_size:3d} {h.bit_depth:3d} "
            f"{b.start_line:6d} {b.block_height:6d} {h.data_size:7d}"
        )
    print()


def main() -> int:
    """Dump the oracle stream and the native stream side by side."""
    name = sys.argv[1] if len(sys.argv) > 1 else "red"
    limit = int(sys.argv[2]) if len(sys.argv) > 2 else 16

    import pipeline
    from ppm import read_ppm
    from settings import PrintSettings

    w, h, _mx, px = read_ppm(io.BytesIO((FIX / f"{name}.ppm").read_bytes()))
    s = PrintSettings()
    s.page_size = "Letter"
    buf = io.BytesIO()
    pipeline.filter_page(w, h, px, s, buf)

    print(f"=== {name} ===")
    dump("ORACLE", (FIX / f"{name}.xl2hb").read_bytes(), limit)
    dump("NATIVE", buf.getvalue(), limit)
    return 0


if __name__ == "__main__":
    sys.exit(main())
