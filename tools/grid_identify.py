#!/usr/bin/env python3
"""Uniquely identify the grid per setting, using all planes and several ramps.

R/G/B ramps still leave some grids indistinguishable because only the M and Y
planes are checked.  This tool adds the C and K planes and a grey ramp, so the
candidate set collapses to one grid.  Both plain and toner-save dither tables
are searched, since the table choice is a second unknown.

Usage: grid_identify.py
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
from find_luts import scan, unpack  # noqa: E402
from grid_pin_all import GRIDS, ORDER, COL, zero_levels  # noqa: E402
from ramp_measure import find_phase, plane_cycle  # noqa: E402

RAW = HERE.parent / "ref" / "brhl3040cnfilter.bin"
FIX = Path("/mnt/ssd/bprobe")
SRC_WIDTH = 5100
HEIGHT = 6564
BARS = 60
STEP = SRC_WIDTH // BARS
VALUES = [round(i * 255 / (BARS - 1)) for i in range(BARS)]
# Each ramp is an RGB triple generator; `r`,`g`,`b` walk one axis, `gray` all.
RAMPS = {
    "r": lambda v: (v, 0, 0), "g": lambda v: (0, v, 0), "b": lambda v: (0, 0, v),
    "gray": lambda v: (v, v, v),
}
PLANES = ["K", "C", "M", "Y"]

SETTINGS = [
    ("Normal gray=ON ", ["--matching", "Normal", "--gray", "ON"]),
    ("Normal gray=OFF", ["--matching", "Normal", "--gray", "OFF"]),
    ("Vivid  gray=ON ", ["--matching", "Vivid", "--gray", "ON"]),
    ("Vivid  gray=OFF", ["--matching", "Vivid", "--gray", "OFF"]),
    ("None   gray=ON ", ["--matching", "None", "--gray", "ON"]),
    ("None   gray=OFF", ["--matching", "None", "--gray", "OFF"]),
]


def build_ppm(ramp: str) -> bytes:
    """A 60-bar ramp at the paper's real width."""
    row = bytearray()
    for v in VALUES:
        row += bytes(RAMPS[ramp](v)) * STEP
    return b"P6\n%d %d\n255\n" % (SRC_WIDTH, HEIGHT) + bytes(row) * HEIGHT


def main() -> int:
    """Report the unique grid (and dither table) per setting."""
    raw = RAW.read_bytes()
    weights = load_weights()
    tables = {}
    for ts in (False, True):
        tables[ts] = dither.load_dither_tables(str(HERE.parent / "hl3040cn" / "src" / "lut"),
                                               fine=False, toner_save=ts)
    cands = sorted(set(scan(raw)) | set(GRIDS))
    preds = {off: {r: interp_exact(unpack(raw, off), weights,
                                   np.array([list(RAMPS[r](v)) for v in VALUES]), ORDER)
                   for r in RAMPS} for off in cands}
    ppm = {r: Path(f"/tmp/ident_{r}.ppm") for r in RAMPS}
    for r in RAMPS:
        ppm[r].write_bytes(build_ppm(r))
    for label, flags in SETTINGS:
        # Collect pattern-exact level sets per (ramp, plane) for each dither table.
        obs_sets = {}
        for r in RAMPS:
            out = Path(f"/tmp/ident_{r}.xl2hb")
            subprocess.run([sys.executable, str(HERE / "oracle_run.py"), str(ppm[r]), str(out), *flags],
                           check=True, capture_output=True)
            (FIX / f"ramp_ident_{r}.xl2hb").write_bytes(out.read_bytes())
        for ts, tbl in tables.items():
            zsets = {}
            for r in RAMPS:
                for plane in PLANES:
                    obs = plane_cycle(f"ramp_ident_{r}", plane, 10**6)
                    if obs is None:
                        zsets[(r, plane)] = None
                        continue
                    table = tbl[plane]
                    phase = find_phase(obs, table, 30 * STEP, 31 * STEP)
                    zsets[(r, plane)] = [zero_levels(obs, table, bi * STEP, (bi + 1) * STEP, phase)
                                         for bi in range(BARS)]
            survivors = []
            for off in cands:
                ok = True
                for (r, plane), zs in zsets.items():
                    if zs is None:
                        continue
                    col = COL[plane]
                    if any(int(preds[off][r][bi, col]) not in zs[bi] for bi in range(BARS)):
                        ok = False
                        break
                if ok:
                    survivors.append(off)
            if survivors:
                named = ", ".join(f"0x{o:x}({GRIDS.get(o, '?')})" for o in survivors)
                print(f"{label} ts={int(ts)} -> {named}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
