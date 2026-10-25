#!/usr/bin/env python3
"""Compare plane bitmaps across fixtures, the port and the 4150 oracle.

Hashing each plane's first scanline makes duplicates and mis-identifications
visible at a glance.  The 4150 fixtures matter because the port is a port of
the 4150 driver: if the port reproduces the 4150 oracle but not the 3040 one,
the defect is a genuine 3040 difference, not a porting error.
"""
from __future__ import annotations

import hashlib
import io
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))
sys.path.insert(0, str(HERE.parent / "hl3040cn" / "src"))

import pclxl  # noqa: E402
import rle_decode  # noqa: E402
from band import decode_blocks  # noqa: E402

FIX = Path("/mnt/ssd/bprobe")
WIDTH = 5120
LINE_BYTES = WIDTH // 8


def planes(blob: bytes) -> dict[str, tuple[str, float, int]]:
    """Per plane: hash of the first scanline, its density, and its word width."""
    out: dict[str, tuple[str, float, int]] = {}
    for b in decode_blocks(pclxl.parse(blob)):
        if b.plane_name in out or not b.entries:
            continue
        cs = b.header.comp_size
        dec = rle_decode.decode_10bit if cs == 10 else (rle_decode.decode_12bit if cs == 12 else None)
        if dec is None:
            out[b.plane_name] = ("(cs=%d, kein Decoder)" % cs, -1.0, cs)
            continue
        raw = dec(b.entries[0], LINE_BYTES)
        bits = np.unpackbits(np.frombuffer(raw, np.uint8))[:WIDTH]
        out[b.plane_name] = (hashlib.sha256(bits.tobytes()).hexdigest()[:12], float(bits.mean()), cs)
    return out


def main() -> int:
    """Print per-plane hashes for oracle fixtures and the native pipeline."""
    for name in ("red", "grn", "blu", "cyn", "mag", "yel"):
        for tag, path in (("3040", FIX / f"{name}.xl2hb"), ("4150", FIX / f"{name}_4150.xl2hb")):
            if not path.exists():
                continue
            p = planes(path.read_bytes())
            desc = "  ".join(f"{k}:{v[0]}(d={v[1]:.3f},cs={v[2]})" for k, v in sorted(p.items()))
            print(f"{name:5s} {tag}: {desc}")
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
