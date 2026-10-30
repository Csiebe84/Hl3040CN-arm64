#!/usr/bin/env python3
"""Pin all 14 colour settings to the grid the oracle actually loads.

The port's `extract_blobs.py` names the 14 embedded grids by position, and the
names are shifted: the oracle's default settings load 0xa7c5e, which the port
calls `srgb_ig_density2` and never selects for them.  For each setting family
this tool runs one 60-bar R ramp through the oracle and finds the grid whose
interpolated M/Y curve reproduces the ramp's dots exactly (0 misses).  The
dither table is searched too, since grey handling may switch it.

Usage: grid_pin_all.py
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
from exact_interp import interp_exact, load_weights  # noqa: E402
from find_luts import unpack  # noqa: E402
from ramp_measure import find_phase, plane_cycle  # noqa: E402

RAW = HERE.parent / "ref" / "brhl3040cnfilter.bin"
FIX = Path("/mnt/ssd/bprobe")
SRC_WIDTH = 5100
HEIGHT = 6564
BARS = 60
VALUES = [round(i * 255 / (BARS - 1)) for i in range(BARS)]
STEP = SRC_WIDTH // BARS
COL = {"K": 3, "C": 0, "M": 1, "Y": 2}
ORDER = (2, 1, 0)

GRIDS = {
    0x2A541: "cmyk_default", 0x47340: "cmyk_ig_default",
    0x814B3: "rgb_default", 0x8AE95: "rgb_density2", 0x94875: "rgb_glossy",
    0xC4A36: "rgb_ig_default", 0x646BB: "rgb_ig_density2", 0x6E0BD: "rgb_ig_glossy",
    0xBB06E: "srgb_default", 0xC4A4E: "srgb_density2", 0xCE466: "srgb_glossy",
    0x9E25C: "srgb_ig_default", 0xA7C5E: "srgb_ig_density2", 0xBB054: "srgb_ig_glossy",
}

SETTINGS = [
    ("Normal gray=ON ", ["--matching", "Normal", "--gray", "ON"]),
    ("Normal gray=OFF", ["--matching", "Normal", "--gray", "OFF"]),
    ("Vivid  gray=ON ", ["--matching", "Vivid", "--gray", "ON"]),
    ("Vivid  gray=OFF", ["--matching", "Vivid", "--gray", "OFF"]),
    ("None   gray=ON ", ["--matching", "None", "--gray", "ON"]),
    ("None   gray=OFF", ["--matching", "None", "--gray", "OFF"]),
    ("Normal ON toner", ["--matching", "Normal", "--gray", "ON", "--toner", "ON"]),
    ("Normal OFF toner", ["--matching", "Normal", "--gray", "OFF", "--toner", "ON"]),
    ("Vivid  ON toner", ["--matching", "Vivid", "--gray", "ON", "--toner", "ON"]),
    ("Vivid  OFF toner", ["--matching", "Vivid", "--gray", "OFF", "--toner", "ON"]),
    ("Normal ON glossy", ["--matching", "Normal", "--gray", "ON", "--media", "Glossy"]),
    ("Normal OFF glossy", ["--matching", "Normal", "--gray", "OFF", "--media", "Glossy"]),
    ("Vivid  ON glossy", ["--matching", "Vivid", "--gray", "ON", "--media", "Glossy"]),
    ("Vivid  OFF glossy", ["--matching", "Vivid", "--gray", "OFF", "--media", "Glossy"]),
]


def zero_levels(obs: np.ndarray, table, x0: int, x1: int, phase: int) -> list[int]:
    """All levels whose tiled pattern matches the window exactly."""
    period = table.width
    w = ((x1 - x0) // period) * period or (x1 - x0)
    tiled = np.tile(table.threshold_matrix, (1, w // period + 2))[:, x0 % period : x0 % period + w]
    h = min(obs.shape[0], table.height)
    th = np.roll(tiled, -phase, axis=0)[:h]
    obs_w = obs[:h, x0 : x0 + w]
    levels = np.arange(256, dtype=np.int32)[:, None, None]
    err = np.count_nonzero(((255 - levels) > th[None]) ^ obs_w[None], axis=(1, 2))
    return (255 - np.nonzero(err == 0)[0]).tolist()


def build_ppm() -> bytes:
    """A 60-bar R ramp at the paper's real width."""
    row = bytearray()
    for v in VALUES:
        row += bytes((v, 0, 0)) * STEP
    return b"P6\n%d %d\n255\n" % (SRC_WIDTH, HEIGHT) + bytes(row) * HEIGHT


def main() -> int:
    """Report the zero-miss grid for every colour setting."""
    raw = RAW.read_bytes()
    weights = load_weights()
    tables = {}
    for fine in (False, True):
        for ts in (False, True):
            tables[(fine, ts)] = dither.load_dither_tables(
                str(HERE.parent / "hl3040cn" / "src" / "lut"), fine=fine, toner_save=ts)
    rgb = np.array([[v, 0, 0] for v in VALUES])
    preds = {name: interp_exact(unpack(raw, off), weights, rgb, ORDER)
             for off, name in GRIDS.items()}
    ppm = Path("/tmp/grid_pin_all.ppm")
    ppm.write_bytes(build_ppm())
    for label, flags in SETTINGS:
        out = Path("/tmp/grid_pin_all.xl2hb")
        subprocess.run([sys.executable, str(HERE / "oracle_run.py"), str(ppm), str(out), *flags],
                       check=True, capture_output=True)
        (FIX / "ramp_pinall.xl2hb").write_bytes(out.read_bytes())
        results = []
        for (fine, ts), tbl in tables.items():
            obs = {p: plane_cycle("ramp_pinall", p, 10**6) for p in ("M", "Y")}
            phases = {p: find_phase(obs[p], tbl[p], 30 * STEP, 31 * STEP) for p in ("M", "Y")}
            zs = {p: [zero_levels(obs[p], tbl[p], bi * STEP, (bi + 1) * STEP, phases[p])
                      for bi in range(BARS)] for p in ("M", "Y")}
            for name, ink in preds.items():
                miss = sum(1 for p in ("M", "Y") for bi in range(BARS)
                           if int(ink[bi, COL[p]]) not in zs[p][bi])
                results.append((miss, name, f"fine={fine},ts={ts}"))
        results.sort()
        best = results[0] if results else (999, "NONE", "")
        others = " ".join(f"{n}[{t}]({m})" for m, n, t in results[1:3])
        print(f"{label} -> {best[1]} [{best[2]}] misses={best[0]}   next: {others}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
