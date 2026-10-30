#!/usr/bin/env python3
"""Map the BRGray=OFF replacement boundary over a 2D family of probes.

Runs one oracle pass per (chroma) family with --gray ON and --gray OFF and
reports, for each probe, whether the output changed (replaced) together with
the profile-grid CMYK.  The families are (m+d, m, m) over d in a list and m in
a brightness range, which is where the boundary lives.

Usage: graytol_map.py <name> <dlist-csv> [mstep]
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

import color_lut  # noqa: E402
import dither  # noqa: E402
from plane_all import rows  # noqa: E402
from ramp_measure import find_phase, solve_window  # noqa: E402

FIX = Path("/mnt/ssd/bprobe")
LUT_DIR = HERE.parent / "hl3040cn" / "src" / "lut"
SW, HEIGHT = 5100, 6564
PLANES = ("K", "C", "M", "Y")


def build_ppm(colors):
    step = SW // len(colors)
    row = bytearray()
    for c in colors:
        row += bytes(c) * step
    return b"P6\n%d %d\n255\n" % (SW, HEIGHT) + bytes(row) * HEIGHT


def measure(name, colors, tables):
    step = SW // len(colors)
    m = {}
    for p in PLANES:
        obs = rows(name, p)
        if obs is None:
            continue
        mid = len(colors) // 2
        ph = find_phase(obs, tables[p], mid * step, (mid + 1) * step)
        m[p] = np.array([solve_window(obs, tables[p], bi * step, (bi + 1) * step, ph)[0]
                         for bi in range(len(colors))])
    return m


def main() -> int:
    name = sys.argv[1]
    ds = [int(x) for x in sys.argv[2].split(",")]
    mstep = int(sys.argv[3]) if len(sys.argv) > 3 else 1
    colors = []
    for d in ds:
        for m in range(0, 256 - d, mstep):
            colors.append((m + d, m, m))
    tables = dither.load_dither_tables(str(LUT_DIR), fine=False, toner_save=False)
    prof = color_lut.ColorTable("rgb", improve_gray=True, gray_replace=False)
    rgb = np.array(colors, dtype=np.uint8).reshape(-1)
    k, c, m_, y = color_lut.rgb_to_cmyk_lut_arr(rgb, len(colors), prof)
    P = 255 - np.stack([k, c, m_, y], axis=1)

    ppm = Path(f"/tmp/{name}.ppm")
    ppm.write_bytes(build_ppm(colors))
    res = {}
    for g in ("ON", "OFF"):
        dst = Path(f"/tmp/{name}_{g}.xl2hb")
        subprocess.run([sys.executable, str(HERE / "oracle_run.py"), str(ppm), str(dst),
                        "--matching", "Normal", "--gray", g], check=True, capture_output=True)
        (FIX / f"{name}_{g}.xl2hb").write_bytes(dst.read_bytes())
        res[g] = measure(f"{name}_{g}", colors, tables)

    for bi, c_ in enumerate(colors):
        common = [p for p in PLANES if p in res["ON"] and p in res["OFF"]]
        on = np.array([int(res["ON"][p][bi]) for p in common])
        off = np.array([int(res["OFF"][p][bi]) for p in common])
        repl = int(np.abs(on - off).max()) if len(common) else 0
        print(f"{str(c_):>16} d={max(c_)-min(c_):3d} prof={P[bi].tolist()} "
              f"maxCMY={int(P[bi,1:].max()):3d} K={int(P[bi,0]):3d} changed={repl:3d} "
              f"{'JA' if repl else 'no'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
