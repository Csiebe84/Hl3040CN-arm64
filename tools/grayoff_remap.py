#!/usr/bin/env python3
"""Test whether BRGray=OFF is the grid plus a per-channel input remap.

BRGray=ON reproduces exactly with grid 0xa7c5e.  BRGray=OFF needs a different
tone response on the same input; this tool asks whether that response is a
per-channel input remap applied before the 3D lookup.  It derives the remap
from the oracle's R ramp (all four planes) and then verifies it against the
oracle's G, B and grey ramps, so a curve that only fits R is rejected.

Usage: grayoff_remap.py
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
from grid_pin_all import ORDER, COL  # noqa: E402
from ramp_measure import find_phase, plane_cycle, solve_window  # noqa: E402

RAW = HERE.parent / "ref" / "brhl3040cnfilter.bin"
FIX = Path("/mnt/ssd/bprobe")
SW, HEIGHT, BARS = 5100, 6564, 60
STEP = SW // BARS
VALUES = [round(i * 255 / (BARS - 1)) for i in range(BARS)]
RAMPS = {"r": lambda v: (v, 0, 0), "g": lambda v: (0, v, 0), "b": lambda v: (0, 0, v),
         "gray": lambda v: (v, v, v)}
PLANES = ["K", "C", "M", "Y"]


def build_ppm(ramp: str) -> bytes:
    row = bytearray()
    for v in VALUES:
        row += bytes(RAMPS[ramp](v)) * STEP
    return b"P6\n%d %d\n255\n" % (SW, HEIGHT) + bytes(row) * HEIGHT


def measure(name: str, tables) -> dict[str, np.ndarray]:
    """Per-bar ink level for every plane of one oracle fixture."""
    out = {}
    for plane in PLANES:
        obs = plane_cycle(name, plane, 10**6)
        if obs is None:
            continue
        table = tables[plane]
        phase = find_phase(obs, table, 30 * STEP, 31 * STEP)
        out[plane] = np.array([solve_window(obs, table, bi * STEP, (bi + 1) * STEP, phase)[0]
                               for bi in range(BARS)])
    return out


def main() -> int:
    raw = RAW.read_bytes()
    weights = load_weights()
    tables = dither.load_dither_tables(str(HERE.parent / "hl3040cn" / "src" / "lut"),
                                        fine=False, toner_save=False)
    ppm = {r: Path(f"/tmp/gor_{r}.ppm") for r in RAMPS}
    for r in RAMPS:
        ppm[r].write_bytes(build_ppm(r))
    meas = {}
    for r in RAMPS:
        out = Path(f"/tmp/gor_{r}.xl2hb")
        subprocess.run([sys.executable, str(HERE / "oracle_run.py"), str(ppm[r]), str(out),
                        "--matching", "Normal", "--gray", "OFF"], check=True, capture_output=True)
        (FIX / f"ramp_gor_{r}.xl2hb").write_bytes(out.read_bytes())
        meas[r] = measure(f"ramp_gor_{r}", tables)
    for grid_off in (0xA7C5E, 0xC4A36):
        grid = unpack(raw, grid_off)
        # interp(grid, u,0,0) for every u: the R-axis response as a function of u.
        ax = interp_exact(grid, weights, np.array([[u, 0, 0] for u in range(256)]), ORDER)
        # Derive remap from the R ramp: pick the u whose plane vector is closest.
        present = [p for p in PLANES if p in meas["r"]]
        f = []
        for bi, v in enumerate(VALUES):
            want = np.array([meas["r"][p][bi] for p in present])
            err = np.abs(ax[:, [COL[p] for p in present]] - want[None, :]).sum(axis=1)
            f.append(int(np.argmin(err)))
        f = np.array(f)
        # Verify on all ramps by applying f to each channel before the lookup.
        total_miss = 0
        report = []
        for r in RAMPS:
            c = {"r": 0, "g": 1, "b": 2}.get(r)
            # f is indexed by bar; the ramps use exactly the VALUES at each bar.
            if c is not None:
                rgb = np.array([[f[bi] if j == c else 0 for j in range(3)]
                                for bi in range(BARS)])
            else:
                rgb = np.array([[f[bi]] * 3 for bi in range(BARS)])
            ink = interp_exact(grid, weights, rgb, ORDER)
            miss = sum(1 for p in PLANES if p in meas[r] for bi in range(BARS)
                       if int(ink[bi, COL[p]]) != meas[r][p][bi])
            total_miss += miss
            report.append(f"{r}:{miss}")
        print(f"grid 0x{grid_off:x}: f=[{f[0]},{f[1]},{f[4]},{f[10]},{f[20]},{f[30]},{f[45]},{f[59]}]"
              f"  mismatched bars -> {' '.join(report)}  total={total_miss}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
