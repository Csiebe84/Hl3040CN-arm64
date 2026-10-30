#!/usr/bin/env python3
"""Exact solid-page ink of a plane, decoding every block of the capture.

The per-block helpers only see the first block, which for the short Y blocks
is a handful of rows and makes the ink fit noisy.  This decodes all blocks of
one plane into one tall bitmap and fits the ink against the tiled dither table
over the whole page, which is exact for a solid colour.

Usage: import and call solid_ink(name, plane, table) -> (ink, err, rows)
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "src"))
sys.path.insert(0, str(HERE.parent / "hl3040cn" / "src"))

import pclxl  # noqa: E402
import rle_decode  # noqa: E402
from band import decode_blocks  # noqa: E402
from decode20 import decode_20bit  # noqa: E402

FIX = Path("/mnt/ssd/bprobe")
WIDTH = 5120
LINE_BYTES = WIDTH // 8
SW = 5100
DECODERS = {10: rle_decode.decode_10bit, 12: rle_decode.decode_12bit, 20: decode_20bit}


def plane_bitmap(name: str, plane: str) -> np.ndarray | None:
    """All rows of every block of `plane`, concatenated, as a bool array."""
    rows = []
    for b in decode_blocks(pclxl.parse((FIX / f"{name}.xl2hb").read_bytes())):
        if b.plane_name != plane or not b.entries:
            continue
        dec = DECODERS.get(b.header.comp_size)
        if dec is None:
            return None
        for e in b.entries:
            rows.append(np.unpackbits(np.frombuffer(dec(e, LINE_BYTES), np.uint8))[:SW].astype(bool))
    if not rows:
        return None
    return np.stack(rows)


def solid_ink(obs: np.ndarray, table) -> tuple[int, int]:
    """Best (ink, error) for a solid-colour plane over the whole decoded bitmap."""
    period = table.width
    reps = SW // period + 2
    tiled = np.tile(table.threshold_matrix, (1, reps))[:, :SW]
    h = min(obs.shape[0], table.height)
    levels = np.arange(256, dtype=np.int32)[:, None, None]
    obs_w = obs[:h, :SW]
    best = (10**18, None)
    for ph in range(table.height):
        th = np.roll(tiled, -ph, axis=0)[:h]
        dots = (255 - levels) > th[None, :, :]
        err = np.count_nonzero(dots ^ obs_w[None, :, :], axis=(1, 2))
        i = int(np.argmin(err))
        if err[i] < best[0]:
            best = (int(err[i]), 255 - i)
    return best[1], best[0]


def main() -> int:
    name = sys.argv[1]
    for plane in ("K", "C", "M", "Y"):
        obs = plane_bitmap(name, plane)
        if obs is None:
            print(f"{name} {plane}: absent")
            continue
        print(f"{name} {plane}: rows={obs.shape[0]} density={obs.mean():.5f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
