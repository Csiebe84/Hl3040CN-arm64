#!/usr/bin/env python3
"""For each probe, which of the 14 grids reproduces the oracle's OFF ink exactly?

Reads the fixtures written by graytol_sweep.py (name_ON / name_OFF), recovers
the OFF ink per bar, interpolates every embedded grid at the probe colour, and
reports the grids whose ink matches the oracle exactly (L1 = 0).

Usage: graytol_bestgrid.py <name> <probefile>
"""
from __future__ import annotations

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
from grid_pin_all import COL, GRIDS, ORDER  # noqa: E402
from plane_all import rows  # noqa: E402
from ramp_measure import find_phase, solve_window  # noqa: E402

FIX = Path("/mnt/ssd/bprobe")
RAW = HERE.parent / "ref" / "brhl3040cnfilter.bin"
LUT_DIR = HERE.parent / "hl3040cn" / "src" / "lut"
SW = 5100
PLANES = ("K", "C", "M", "Y")


def main() -> int:
    name = sys.argv[1]
    colors = []
    for line in Path(sys.argv[2]).read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            colors.append(tuple(int(x) for x in line.split()))
    step = SW // len(colors)
    tables = dither.load_dither_tables(str(LUT_DIR), fine=False, toner_save=False)
    weights = load_weights()
    raw = RAW.read_bytes()

    meas = {}
    err = {}
    for g in ("ON", "OFF"):
        m = {}
        e = {}
        for p in PLANES:
            obs = rows(f"{name}_{g}", p)
            if obs is None:
                continue
            mid = len(colors) // 2
            ph = find_phase(obs, tables[p], mid * step, (mid + 1) * step)
            vals, errs = [], []
            for bi in range(len(colors)):
                ink, er = solve_window(obs, tables[p], bi * step, (bi + 1) * step, ph)
                vals.append(ink)
                errs.append(er)
            m[p] = np.array(vals)
            e[p] = np.array(errs)
        meas[g] = m
        err[g] = e

    rgb = np.array(colors)
    grids = {off: interp_exact(unpack(raw, off), weights, rgb, ORDER) for off in GRIDS}
    for bi, c in enumerate(colors):
        off = np.array([int(meas["OFF"][p][bi]) for p in PLANES])
        offe = np.array([int(err["OFF"][p][bi]) for p in PLANES])
        on = np.array([int(meas["ON"][p][bi]) for p in PLANES])
        changed = int(np.abs(off - on).max())
        matches = []
        best = (10**9, None)
        for off_off, gi in grids.items():
            ink = np.array([int(gi[bi, COL[p]]) for p in PLANES])
            d = int(np.abs(ink - off).sum())
            if d < best[0]:
                best = (d, off_off)
            if d == 0:
                matches.append(GRIDS[off_off])
        names = ",".join(matches) if matches else f"none (best {GRIDS[best[1]]} d={best[0]})"
        print(f"{str(c):>16} d={max(c)-min(c):3d} dONOFF={changed:3d} OFF={off.tolist()} err={offe.tolist()} -> {names}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
