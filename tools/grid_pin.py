#!/usr/bin/env python3
"""Pin the setting -> grid mapping with one oracle ramp per setting.

The port's `extract_blobs.py` names the 14 embedded grids by position, but the
oracle's default settings load grid 0xa7c5e, which the port never selects for
them.  For each setting family this tool runs one 60-bar R ramp through the
oracle, measures the M and Y ink per bar, and matches that curve against every
grid's interpolated prediction (the transformation is already bit-exact, so a
grid's prediction is trustworthy).  The best match names the grid.

Usage: grid_pin.py
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
from ramp_measure import find_phase, plane_cycle, solve_window  # noqa: E402

RAW = HERE.parent / "ref" / "brhl3040cnfilter.bin"
FIX = Path("/mnt/ssd/bprobe")
SRC_WIDTH = 5100
HEIGHT = 6564
BARS = 60
VALUES = [round(i * 255 / (BARS - 1)) for i in range(BARS)]
COL = {"K": 3, "C": 0, "M": 1, "Y": 2}

# The 14 verified data offsets (== where each `color_data/*_lut.bin` sits in the
# binary, `raw.find(file)`) plus the structural candidates `find_luts.scan` adds.
CANDS = [
    0x2A541, 0x47340, 0x814B3, 0x8AE95, 0xC4A36, 0x646BB, 0x6E0BD, 0xBB06E,
    0xC4A4E, 0xCE466, 0x9E25C, 0xA7C5E, 0xBB054,
    0x77ABD, 0xB165C, 0xCE414, 0x33EBE, 0x3D8BF, 0x5A6BE,
]

SETTINGS = [
    ("rgb_ig_default  ", ["--matching", "Normal", "--gray", "ON"]),
    ("rgb_default     ", ["--matching", "Normal", "--gray", "OFF"]),
    ("srgb_ig_default ", ["--matching", "Vivid", "--gray", "ON"]),
    ("srgb_default    ", ["--matching", "Vivid", "--gray", "OFF"]),
    ("cmyk_ig_default ", ["--matching", "None", "--gray", "ON"]),
    ("cmyk_default    ", ["--matching", "None", "--gray", "OFF"]),
    ("rgb_ig_density2 ", ["--matching", "Normal", "--gray", "ON", "--toner", "ON"]),
    ("rgb_ig_glossy   ", ["--matching", "Normal", "--gray", "ON", "--media", "Glossy"]),
    ("rgb_density2    ", ["--matching", "Normal", "--gray", "OFF", "--toner", "ON"]),
    ("rgb_glossy      ", ["--matching", "Normal", "--gray", "OFF", "--media", "Glossy"]),
    ("srgb_ig_density2", ["--matching", "Vivid", "--gray", "ON", "--toner", "ON"]),
    ("srgb_ig_glossy  ", ["--matching", "Vivid", "--gray", "ON", "--media", "Glossy"]),
    ("srgb_density2   ", ["--matching", "Vivid", "--gray", "OFF", "--toner", "ON"]),
    ("srgb_glossy     ", ["--matching", "Vivid", "--gray", "OFF", "--media", "Glossy"]),
]


def build_ppm() -> bytes:
    """A 60-bar R ramp at the paper's real width."""
    row = bytearray()
    for v in VALUES:
        row += bytes((v, 0, 0)) * (SRC_WIDTH // BARS)
    return b"P6\n%d %d\n255\n" % (SRC_WIDTH, HEIGHT) + bytes(row) * HEIGHT


def measure(name: str, tables: dict) -> dict[str, np.ndarray]:
    """M and Y ink per bar of the oracle ramp fixture `ramp_<name>`."""
    out = {}
    step = SRC_WIDTH // BARS
    for plane in ("M", "Y"):
        obs = plane_cycle(name, plane, 10**6)
        table = tables[plane]
        phase = find_phase(obs, table, 30 * step, 31 * step)
        inks = [solve_window(obs, table, bi * step, (bi + 1) * step, phase)[0] for bi in range(BARS)]
        out[plane] = np.array(inks)
    return out


def main() -> int:
    """Run one ramp per setting and report the best-matching grid."""
    raw = RAW.read_bytes()
    weights = load_weights()
    tables = dither.load_dither_tables(str(HERE.parent / "hl3040cn" / "src" / "lut"), fine=False, toner_save=False)
    rgb = np.array([[v, 0, 0] for v in VALUES])
    grids = {}
    for off in CANDS:
        g = unpack(raw, off)
        ink = interp_exact(g, weights, rgb, (2, 1, 0))
        grids[off] = (ink[:, COL["M"]], ink[:, COL["Y"]])
    ppm = build_ppm()
    tmp = Path("/tmp/grid_pin_ramp.ppm")
    tmp.write_bytes(ppm)
    for label, flags in SETTINGS:
        out = Path("/tmp/grid_pin.xl2hb")
        subprocess.run([sys.executable, str(HERE / "oracle_run.py"), str(tmp), str(out), *flags],
                       check=True, capture_output=True)
        (FIX / "ramp_pin.xl2hb").write_bytes(out.read_bytes())
        meas = measure("ramp_pin", tables)
        scored = []
        for off, (pm, py) in grids.items():
            err = int(np.abs(pm - meas["M"]).sum() + np.abs(py - meas["Y"]).sum())
            scored.append((err, off))
        scored.sort()
        top = "  ".join(f"0x{o:x}({e})" for e, o in scored[:3])
        print(f"{label} -> {top}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
