#!/usr/bin/env python3
"""Pin the setting -> grid name mapping, solving grid AND dither table jointly.

`ramp_measure`'s ink solve needs the dither table the oracle actually used,
which itself depends on the settings (plain/toner/gray/fine).  For each
profile x grey-handling combination this tool runs one R ramp, then searches
every grid candidate together with every port dither table for the pair that
reproduces the ramp with zero residual.  A unique zero-residual pair names both
the grid and the table.

Usage: grid_name_pin.py
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
from ramp_measure import find_phase, plane_cycle, solve_window  # noqa: E402

RAW = HERE.parent / "ref" / "brhl3040cnfilter.bin"
FIX = Path("/mnt/ssd/bprobe")
SRC_WIDTH = 5100
HEIGHT = 6564
BARS = 60
VALUES = [round(i * 255 / (BARS - 1)) for i in range(BARS)]
COL = {"K": 3, "C": 0, "M": 1, "Y": 2}

GRID_OFFSETS = {
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
]


def build_ppm() -> bytes:
    """A 60-bar R ramp at the paper's real width."""
    row = bytearray()
    for v in VALUES:
        row += bytes((v, 0, 0)) * (SRC_WIDTH // BARS)
    return b"P6\n%d %d\n255\n" % (SRC_WIDTH, HEIGHT) + bytes(row) * HEIGHT


def main() -> int:
    """For each setting, report grid x dither-table pairs with zero residual."""
    raw = RAW.read_bytes()
    weights = load_weights()
    all_tables = {}
    for fine in (False, True):
        for ts in (False, True):
            all_tables[(fine, ts)] = dither.load_dither_tables(
                str(HERE.parent / "hl3040cn" / "src" / "lut"), fine=fine, toner_save=ts)
    rgb = np.array([[v, 0, 0] for v in VALUES])
    preds = {}
    for off, name in GRID_OFFSETS.items():
        ink = interp_exact(unpack(raw, off), weights, rgb, (2, 1, 0))
        preds[name] = (ink[:, COL["M"]], ink[:, COL["Y"]])
    step = SRC_WIDTH // BARS
    ppm = Path("/tmp/grid_name_pin.ppm")
    ppm.write_bytes(build_ppm())
    for label, flags in SETTINGS:
        out = Path("/tmp/grid_name_pin.xl2hb")
        subprocess.run([sys.executable, str(HERE / "oracle_run.py"), str(ppm), str(out), *flags],
                       check=True, capture_output=True)
        (FIX / "ramp_namepin.xl2hb").write_bytes(out.read_bytes())
        hits = []
        for (fine, ts), tables in all_tables.items():
            try:
                obs_m = plane_cycle("ramp_namepin", "M", 10**6)
                obs_y = plane_cycle("ramp_namepin", "Y", 10**6)
            except Exception:
                continue
            ph_m = find_phase(obs_m, tables["M"], 30 * step, 31 * step)
            ph_y = find_phase(obs_y, tables["Y"], 30 * step, 31 * step)
            meas_m = np.array([solve_window(obs_m, tables["M"], bi * step, (bi + 1) * step, ph_m)[0] for bi in range(BARS)])
            meas_y = np.array([solve_window(obs_y, tables["Y"], bi * step, (bi + 1) * step, ph_y)[0] for bi in range(BARS)])
            for name, (pm, py) in preds.items():
                e = int(np.abs(pm - meas_m).sum() + np.abs(py - meas_y).sum())
                if e <= 2:
                    hits.append((e, name, f"fine={fine},ts={ts}"))
        hits.sort()
        top = "  ".join(f"{n}[{t}]({e})" for e, n, t in hits[:4]) or "NONE"
        print(f"{label} -> {top}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
