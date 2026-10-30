#!/usr/bin/env python3
"""Measure the oracle's per-pixel achromatic rule for BRGray=OFF.

With BRGray=OFF the oracle separates some pixels through the cmyk grid and the
rest through the profile grid.  BRGray=ON always uses the profile grid, so a
pixel is "replaced" exactly when its rendered dots differ between the two
settings.  This tool paints one solid bar per probe colour, runs the oracle
with --gray ON and --gray OFF, recovers the ink of every plane and bar with the
bit-exact dither fit, and reports which bars changed.

Usage: graytol_measure.py <probefile>   (probefile: lines of "r g b")
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
from plane_all import rows  # noqa: E402
from ramp_measure import find_phase, solve_window  # noqa: E402

FIX = Path("/mnt/ssd/bprobe")
LUT_DIR = HERE.parent / "hl3040cn" / "src" / "lut"
SW, HEIGHT = 5100, 6564
PLANES = ("K", "C", "M", "Y")


def build_ppm(colors: list[tuple[int, int, int]]) -> bytes:
    """One equal-width bar per colour, full height."""
    step = SW // len(colors)
    row = bytearray()
    for c in colors:
        row += bytes(c) * step
    row += bytes(colors[-1]) * (SW - len(row) // 3)
    return b"P6\n%d %d\n255\n" % (SW, HEIGHT) + bytes(row) * HEIGHT


def measure(name: str, tables, nbars: int, step: int) -> dict[str, np.ndarray]:
    """Per-bar ink for every plane present in one oracle fixture."""
    out = {}
    for plane in PLANES:
        obs = rows(name, plane)
        if obs is None:
            continue
        table = tables[plane]
        mid = nbars // 2
        phase = find_phase(obs, table, mid * step, (mid + 1) * step)
        out[plane] = np.array(
            [solve_window(obs, table, bi * step, (bi + 1) * step, phase)[0] for bi in range(nbars)]
        )
    return out


def main() -> int:
    probe = Path(sys.argv[1])
    colors = []
    for line in probe.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        colors.append(tuple(int(x) for x in line.split()))
    step = SW // len(colors)
    tables = dither.load_dither_tables(str(LUT_DIR), fine=False, toner_save=False)
    ppm = Path("/tmp/graytol.ppm")
    ppm.write_bytes(build_ppm(colors))
    meas = {}
    for g in ("ON", "OFF"):
        dst = Path(f"/tmp/graytol_{g}.xl2hb")
        subprocess.run(
            [sys.executable, str(HERE / "oracle_run.py"), str(ppm), str(dst), "--matching", "Normal", "--gray", g],
            check=True, capture_output=True,
        )
        (FIX / f"graytol_{g}.xl2hb").write_bytes(dst.read_bytes())
        meas[g] = measure(f"graytol_{g}", tables, len(colors), step)
    planes = sorted(set(meas["ON"]) & set(meas["OFF"]))
    print(f"{'idx':>3} {'pixel':>16} {'maxmin':>6} {'min':>4} {'max':>4}  replaced  ON->OFF deltas")
    for bi, c in enumerate(colors):
        deltas = []
        replaced = False
        for p in planes:
            a, b = int(meas["ON"][p][bi]), int(meas["OFF"][p][bi])
            if a != b:
                replaced = True
                deltas.append(f"{p}:{a}->{b}")
        d = max(c) - min(c)
        print(f"{bi:3d} {str(c):>16} {d:6d} {min(c):4d} {max(c):4d}  {'JA ' if replaced else 'no '}      {' '.join(deltas)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
