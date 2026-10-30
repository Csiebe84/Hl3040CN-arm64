#!/usr/bin/env python3
"""Which grid does the oracle use per input colour, and does gray=OFF switch it?

The six primaries (default rc = Normal/BRGray=OFF) and the colour ramps match
grid 0xa7c5e, but the gray=OFF gray ramp matches grid 0x2a541 (cmyk_default).
This tool feeds a strip of solid patches that walk from pure gray to a
saturated colour and matches each patch against every grid, to find whether the
grid switches with the pixel and where.

Usage: grid_switch.py
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
from grid_pin_all import COL, GRIDS, ORDER  # noqa: E402
from plane_all import rows  # noqa: E402
from ramp_measure import find_phase, solve_window  # noqa: E402

RAW = HERE.parent / "ref" / "brhl3040cnfilter.bin"
FIX = Path("/mnt/ssd/bprobe")
SW, HEIGHT = 5100, 6564
PATCH = 510  # 10 patches across the sheet
PLANES = ("C", "M", "Y", "K")

# Patches: pure gray, then increasing chroma at the same luma, then colours.
PATCHES = [
    ("gray128", (128, 128, 128)), ("g128_2", (128, 128, 126)),
    ("g128_8", (128, 128, 120)), ("g128_32", (128, 128, 96)),
    ("g128_64", (128, 128, 64)), ("red128", (128, 0, 0)),
    ("pink", (128, 64, 64)), ("red", (255, 0, 0)),
    ("gray192", (192, 192, 192)), ("gray64", (64, 64, 64)),
]


def build_ppm() -> bytes:
    row = bytearray()
    for _, (r, g, b) in PATCHES:
        row += bytes((r, g, b)) * PATCH
    return b"P6\n%d %d\n255\n" % (SW, HEIGHT) + bytes(row) * HEIGHT


def main() -> int:
    raw = RAW.read_bytes()
    weights = load_weights()
    tables = dither.load_dither_tables(str(HERE.parent / "hl3040cn" / "src" / "lut"),
                                        fine=False, toner_save=False)
    cands = sorted(set(scan(raw)) | set(GRIDS))
    ppm = Path("/tmp/gridswitch.ppm")
    ppm.write_bytes(build_ppm())
    for g in ("ON", "OFF"):
        name = f"gswitch_{g}"
        dst = Path(f"/tmp/{name}.xl2hb")
        subprocess.run([sys.executable, str(HERE / "oracle_run.py"), str(ppm), str(dst),
                        "--matching", "Normal", "--gray", g], check=True, capture_output=True)
        (FIX / f"{name}.xl2hb").write_bytes(dst.read_bytes())
        meas = {}
        for plane in PLANES:
            r = rows(name, plane)
            if r is None:
                meas[plane] = None
                continue
            table = tables[plane]
            x0 = PATCH // 2
            phase = find_phase(r, table, x0, x0 + 100)
            meas[plane] = [solve_window(r, table, i * PATCH + PATCH // 4,
                                        i * PATCH + 3 * PATCH // 4, phase)[0]
                           for i in range(len(PATCHES))]
        print(f"=== gray={g} ===")
        for i, (label, rgb) in enumerate(PATCHES):
            want = {p: (meas[p][i] if meas[p] is not None else 0) for p in PLANES}
            best = []
            for off in cands:
                ink = interp_exact(unpack(raw, off), weights, np.array([list(rgb)]), ORDER)[0]
                e = sum(abs(int(ink[COL[p]]) - want[p]) for p in PLANES)
                best.append((e, off))
            best.sort()
            oracle = " ".join(f"{p}={want[p]:3d}" for p in PLANES)
            top = " ".join(f"0x{o:x}:{e}" for e, o in best[:2])
            print(f"  {label:9s} {str(rgb):16s} oracle {oracle}  -> {top}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
