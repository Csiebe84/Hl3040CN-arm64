#!/usr/bin/env python3
"""Decode any plane of an oracle capture, picking the decoder by comp_size.

`ramp_measure.plane_cycle` covers the 12-bit (K/Y) and 10-bit (M) planes;
`decode20` covers the 20-bit cyan plane.  This helper exposes all four behind
one call so a capture's planes can be compared bit for bit.

Usage: plane_all.py <name> <plane>
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "src"))

import pclxl  # noqa: E402
import rle_decode  # noqa: E402
from band import decode_blocks  # noqa: E402
from decode20 import decode_20bit  # noqa: E402

FIX = Path("/mnt/ssd/bprobe")
WIDTH = 5120
LINE_BYTES = WIDTH // 8
DECODERS = {10: rle_decode.decode_10bit, 12: rle_decode.decode_12bit, 20: decode_20bit}


def rows(name: str, plane: str, want: int = 10**6) -> np.ndarray | None:
    """First `want` decoded scanlines of the plane's first block as bool rows."""
    for b in decode_blocks(pclxl.parse((FIX / f"{name}.xl2hb").read_bytes())):
        if b.plane_name != plane or not b.entries:
            continue
        dec = DECODERS.get(b.header.comp_size)
        if dec is None:
            return None
        out = [np.unpackbits(np.frombuffer(dec(e, LINE_BYTES), np.uint8))[:WIDTH].astype(bool)
               for e in b.entries]
        return np.stack(out)
    return None


def main() -> int:
    r = rows(sys.argv[1], sys.argv[2])
    if r is None:
        print("absent")
        return 0
    print(f"rows={r.shape[0]} density={r.mean():.6f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
