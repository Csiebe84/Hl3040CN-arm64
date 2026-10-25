#!/usr/bin/env python3
"""List every raster plane of every fixture: word width, density, block count.

Which planes a page carries, and in what order, differs per colour: magenta
opens with a nearly empty 20-bit C plane while red opens with a 10-bit M
plane.  A tool that keys planes by name and keeps the first one therefore
reports the wrong plane.  This dumps them all, in stream order, and decodes
only the widths that have a validated decoder, so nothing is silently
mis-measured.
"""
from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))

import pclxl  # noqa: E402
import rle_decode  # noqa: E402
from band import decode_blocks  # noqa: E402

FIX = Path("/mnt/ssd/bprobe")
WIDTH = 5120
LINE_BYTES = WIDTH // 8
DECODERS = {10: rle_decode.decode_10bit, 12: rle_decode.decode_12bit}


def density(bitmap: bytes) -> float:
    """Fraction of set bits in a packed 1bpp line."""
    return float(np.unpackbits(np.frombuffer(bitmap, np.uint8)).mean())


def main() -> int:
    """Print per-plane statistics for each fixture."""
    for name in sys.argv[1:] or ["red", "grn", "blu", "cyn", "mag", "yel"]:
        try:
            blob = (FIX / f"{name}.xl2hb").read_bytes()
        except FileNotFoundError:
            print(f"{name}: Fixture fehlt")
            continue
        blocks = decode_blocks(pclxl.parse(blob))
        counts = Counter(b.plane_name for b in blocks)
        print(f"=== {name}: {len(blocks)} Bloecke {dict(counts)} ===")
        seen: set[str] = set()
        for b in blocks:
            cs = b.header.comp_size
            tag = f"{b.plane_name}(cs={cs})"
            if tag in seen:
                continue
            seen.add(tag)
            dec = DECODERS.get(cs)
            if dec is None or not b.entries:
                print(f"    {tag:12s} kein Decoder / leer")
                continue
            try:
                raw = dec(b.entries[0], LINE_BYTES)
            except rle_decode.RleError as exc:
                print(f"    {tag:12s} Dekodierfehler: {exc}")
                continue
            print(f"    {tag:12s} Zeilen={len(b.entries):5d}  Dichte(erste Zeile)={density(raw):.4f}")
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
