#!/usr/bin/env python3
"""Map each colour setting to the embedded grid the oracle actually loads.

The port's `extract_blobs.py` names the 14 grids by position, but the oracle's
default (BRColorMatching=Normal, BRGray=ON) run reproduces grid 0xa7c5e, which
the port calls `srgb_ig_density2` and never selects for that setting.  This
tool measures the oracle's M and Y ink for all six primaries under one changed
setting at a time and matches the full six-primary signature against every
grid, pinning the setting -> grid mapping empirically.

Usage: grid_map_six.py
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
FIX = Path("/mnt/ssd/bprobe")
WIDTH = 5120
LINE_BYTES = WIDTH // 8
SRC_WIDTH = 5100
DECODERS = {10: rle_decode.decode_10bit, 12: rle_decode.decode_12bit}
PRIMS = {"red": (255, 0, 0), "grn": (0, 255, 0), "blu": (0, 0, 255),
         "cyn": (0, 255, 255), "mag": (255, 0, 255), "yel": (255, 255, 0)}
COL = {"K": 3, "C": 0, "M": 1, "Y": 2}

SETTINGS = [
    ("Normal ON ", ["--matching", "Normal", "--gray", "ON"]),
    ("Normal OFF", ["--matching", "Normal", "--gray", "OFF"]),
    ("Vivid  ON ", ["--matching", "Vivid", "--gray", "ON"]),
    ("Vivid  OFF", ["--matching", "Vivid", "--gray", "OFF"]),
    ("None   ON ", ["--matching", "None", "--gray", "ON"]),
    ("Normal toner", ["--matching", "Normal", "--gray", "ON", "--toner", "ON"]),
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


def ink_level(blob: bytes, plane: str, tables: dict) -> tuple[int, int]:
    """Best (ink, mismatch) for the plane over the source width."""
    obs = plane_rows(blob, plane)
    if obs is None:
        return -1, -1
    t = tables[plane]
    w = (SRC_WIDTH // t.width) * t.width
    tiled = np.tile(t.threshold_matrix, (1, w // t.width + 2))[:, :w]
    h = min(obs.shape[0], t.height)
    levels = np.arange(256, dtype=np.int32)[:, None, None]
    err = np.count_nonzero(((255 - levels) > tiled[:h][None]) ^ obs[:h, :w][None], axis=(1, 2))
    return 255 - int(np.argmin(err)), int(err.min())


def measure(rgb: tuple[int, int, int], flags: list[str], tables: dict) -> dict[str, int]:
    """Run the oracle on a solid colour and read every plane's ink."""
    ppm = FIX / "red.ppm"
    tmp_ppm = Path("/tmp/grid_map_solid.ppm")
    header = f"P6\n{WIDTH} {6564}\n255\n".encode()
    tmp_ppm.write_bytes(header + bytes(rgb) * (WIDTH * 6564))
    out = Path("/tmp/grid_map_solid.xl2hb")
    subprocess.run([sys.executable, str(HERE / "oracle_run.py"), str(tmp_ppm), str(out), *flags],
                   check=True, capture_output=True)
    blob = out.read_bytes()
    return {p: ink_level(blob, p, tables)[0] for p in ("M", "Y", "C", "K")}


def grid_sig(grid: np.ndarray, weights: np.ndarray) -> dict[str, tuple[int, int]]:
    """Per primary, the interpolated (M, Y) ink of the grid."""
    out = {}
    for name, rgb in PRIMS.items():
        ink = interp_exact(grid, weights, np.array([list(rgb)]), (2, 1, 0))[0]
        out[name] = (int(ink[COL["M"]]), int(ink[COL["Y"]]))
    return out


def main() -> int:
    """Report the matching grid offset for each colour setting."""
    raw = RAW.read_bytes()
    weights = load_weights()
    tables = dither.load_dither_tables(str(HERE.parent / "hl3040cn" / "src" / "lut"), fine=False, toner_save=False)
    grids = {off + 2: grid_sig(unpack(raw, off + 2), weights) for off in scan(raw)}
    for label, flags in SETTINGS:
        meas = {}
        for name, rgb in PRIMS.items():
            levels = measure(rgb, flags, tables)
            meas[name] = (levels["M"], levels["Y"])
        # A level is only observable through its dots: accept a grid when every
        # primary is within the +/-1 pattern-ambiguity window.
        def close(sig: dict, m: dict) -> bool:
            return all(abs(sig[n][0] - m[n][0]) <= 1 and abs(sig[n][1] - m[n][1]) <= 1 for n in PRIMS)
        hits = [f"0x{o:x}" for o, sig in grids.items() if close(sig, meas)]
        detail = " ".join(f"{n}={meas[n][0]}/{meas[n][1]}" for n in PRIMS)
        print(f"{label:13s} {detail}  grid={hits or 'NONE'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
