#!/usr/bin/env python3
"""Disambiguate the setting -> grid mapping with R, G and B ramps.

On the R ramp alone several grids give identical dot patterns, so one axis
cannot name the grid.  For each setting this tool runs R, G and B ramps through
the oracle, then keeps only the grid candidates whose interpolated M and Y
levels are pattern-exact for every bar of every axis.  The intersection is the
grid the oracle actually loaded.

Usage: grid_disambiguate.py
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
AXES = {"r": 0, "g": 1, "b": 2}
PLANES = ["M", "Y"]

SETTINGS = [
    ("Normal gray=ON ", ["--matching", "Normal", "--gray", "ON"]),
    ("Normal gray=OFF", ["--matching", "Normal", "--gray", "OFF"]),
    ("Vivid  gray=ON ", ["--matching", "Vivid", "--gray", "ON"]),
    ("Vivid  gray=OFF", ["--matching", "Vivid", "--gray", "OFF"]),
    ("None   gray=ON ", ["--matching", "None", "--gray", "ON"]),
    ("None   gray=OFF", ["--matching", "None", "--gray", "OFF"]),
    ("Normal ON toner", ["--matching", "Normal", "--gray", "ON", "--toner", "ON"]),
    ("Vivid  ON toner", ["--matching", "Vivid", "--gray", "ON", "--toner", "ON"]),
    ("Normal ON glossy", ["--matching", "Normal", "--gray", "ON", "--media", "Glossy"]),
    ("Vivid  ON glossy", ["--matching", "Vivid", "--gray", "ON", "--media", "Glossy"]),
]


def build_ppm(axis: str) -> bytes:
    """A 60-bar ramp along one axis at the paper's real width."""
    c = AXES[axis]
    row = bytearray()
    for v in VALUES:
        row += bytes(v if j == c else 0 for j in range(3)) * STEP
    return b"P6\n%d %d\n255\n" % (SRC_WIDTH, HEIGHT) + bytes(row) * HEIGHT


def main() -> int:
    """For each setting, report the grid candidates consistent with R+G+B."""
    raw = RAW.read_bytes()
    weights = load_weights()
    tables = dither.load_dither_tables(str(HERE.parent / "hl3040cn" / "src" / "lut"),
                                        fine=False, toner_save=False)
    # Candidate set: all scan offsets plus the declared grid offsets.
    cands = sorted(set(scan(raw)) | set(GRIDS))
    preds = {}
    for off in cands:
        sig = {}
        for axis, c in AXES.items():
            rgb = np.array([[v if j == c else 0 for j in range(3)] for v in VALUES])
            sig[axis] = interp_exact(unpack(raw, off), weights, rgb, ORDER)
        preds[off] = sig
    ppm_files = {}
    for axis in AXES:
        p = Path(f"/tmp/disamb_{axis}.ppm")
        p.write_bytes(build_ppm(axis))
        ppm_files[axis] = p
    for label, flags in SETTINGS:
        consistent = set(preds)
        for axis in AXES:
            out = Path(f"/tmp/disamb_{axis}.xl2hb")
            subprocess.run([sys.executable, str(HERE / "oracle_run.py"), str(ppm_files[axis]), str(out), *flags],
                           check=True, capture_output=True)
            (FIX / f"ramp_disamb_{axis}.xl2hb").write_bytes(out.read_bytes())
            for plane in PLANES:
                obs = plane_cycle(f"ramp_disamb_{axis}", plane, 10**6)
                if obs is None:
                    continue  # plane absent for this input colour -> no constraint
                table = tables[plane]
                phase = find_phase(obs, table, 30 * STEP, 31 * STEP)
                zs = [zero_levels(obs, table, bi * STEP, (bi + 1) * STEP, phase) for bi in range(BARS)]
                drop = {off for off in consistent
                        if any(int(preds[off][axis][bi, COL[plane]]) not in zs[bi] for bi in range(BARS))}
                consistent -= drop
        named = sorted(f"0x{o:x}({GRIDS.get(o, '?')})" for o in consistent)
        print(f"{label} -> {named or 'NONE'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
