#!/usr/bin/env python3
"""Pin the setting -> grid mapping by matching oracle primaries to every grid.

The port's `extract_blobs.py` names the 14 embedded grids by position.  This
tool runs the oracle over a fixture containing the R, G and B primaries under
one changed setting at a time, measures the resulting ink, and matches it
against every grid's interpolated primary signature.  That fixes the mapping
empirically instead of by guess.

Usage: oracle_grid_map.py
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "src"))
sys.path.insert(0, str(HERE.parent / "hl3040cn" / "src"))

import dither  # noqa: E402
import pclxl  # noqa: E402
import rle_decode  # noqa: E402
from band import decode_blocks  # noqa: E402
from exact_interp import interp_exact, load_weights  # noqa: E402
from find_luts import scan, unpack  # noqa: E402

RAW = HERE.parent / "ref" / "brhl3040cnfilter.bin"
PPM = Path("/mnt/ssd/bprobe/rgb.ppm")
WIDTH = 5120
LINE_BYTES = WIDTH // 8
SRC_WIDTH = 5100
DECODERS = {10: rle_decode.decode_10bit, 12: rle_decode.decode_12bit}
PRIM_COL = {"red": "M", "grn": "Y", "blu": "M"}
PRIM_RGB = {"red": [255, 0, 0], "grn": [0, 255, 0], "blu": [0, 0, 255]}
# x-run of each primary in rgb.ppm (width 800 each)
RUNS = {"red": (0, 800), "grn": (800, 1600), "blu": (1600, 2400)}
COL = {"K": 3, "C": 0, "M": 1, "Y": 2}

SETTINGS = [
    ("Normal ON ", ["--matching", "Normal", "--gray", "ON"]),
    ("Normal OFF", ["--matching", "Normal", "--gray", "OFF"]),
    ("Vivid  ON ", ["--matching", "Vivid", "--gray", "ON"]),
    ("Vivid  OFF", ["--matching", "Vivid", "--gray", "OFF"]),
    ("None   ON ", ["--matching", "None", "--gray", "ON"]),
    ("None   OFF", ["--matching", "None", "--gray", "OFF"]),
    ("Normal ON toner", ["--matching", "Normal", "--gray", "ON", "--toner", "ON"]),
    ("Normal ON glossy", ["--matching", "Normal", "--gray", "ON", "--media", "Glossy"]),
]


def plane_rows(blob: bytes, plane: str) -> np.ndarray | None:
    """First block of `plane` as bool rows."""
    for b in decode_blocks(pclxl.parse(blob)):
        if b.plane_name == plane and b.entries:
            dec = DECODERS.get(b.header.comp_size)
            if dec is None:
                continue
            return np.stack([
                np.unpackbits(np.frombuffer(dec(e, LINE_BYTES), np.uint8))[:WIDTH].astype(bool)
                for e in b.entries
            ])
    return None


def ink_in_window(blob: bytes, plane: str, tables: dict, x0: int, x1: int) -> tuple[int, int]:
    """Best (ink, mismatch) for a plane over a column window."""
    obs = plane_rows(blob, plane)
    if obs is None:
        return -1, -1
    t = tables[plane]
    span = x1 - x0
    w = (span // t.width) * t.width or span
    tiled = np.tile(t.threshold_matrix, (1, w // t.width + 2))[:, x0 % t.width : x0 % t.width + w]
    h = min(obs.shape[0], t.height)
    th = np.roll(tiled, 0, axis=0)[:h]
    levels = np.arange(256, dtype=np.int32)[:, None, None]
    err = np.count_nonzero(((255 - levels) > th[None]) ^ obs[:h, x0 : x0 + w][None], axis=(1, 2))
    return 255 - int(np.argmin(err)), int(err.min())


def grid_signature(grid: np.ndarray, weights: np.ndarray) -> dict[str, int]:
    """Interpolated ink of the R/G/B primaries under the oracle's convention."""
    out = {}
    for name, rgb in PRIM_RGB.items():
        ink = interp_exact(grid, weights, np.array([rgb]), (2, 1, 0))[0]
        out[name] = int(ink[COL[PRIM_COL[name]]])
    return out


def main() -> int:
    """Run the oracle per setting and report the matching grid offset."""
    raw = RAW.read_bytes()
    weights = load_weights()
    tables = dither.load_dither_tables(str(HERE.parent / "hl3040cn" / "src" / "lut"), fine=False, toner_save=False)
    grids = {off + 2: grid_signature(unpack(raw, off + 2), weights) for off in scan(raw)}
    for label, flags in SETTINGS:
        out = Path("/tmp/rgb_id.xl2hb")
        subprocess.run([sys.executable, str(HERE / "oracle_run.py"), str(PPM), str(out), *flags], check=True)
        blob = out.read_bytes()
        meas = {}
        for name, (x0, x1) in RUNS.items():
            v, _ = ink_in_window(blob, PRIM_COL[name], tables, x0, x1)
            meas[name] = v
        hits = [f"0x{o:x}" for o, sig in grids.items() if sig == meas]
        print(f"{label:18s} red={meas['red']:3d} grn={meas['grn']:3d} blu={meas['blu']:3d}  grid={hits or 'NONE'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
