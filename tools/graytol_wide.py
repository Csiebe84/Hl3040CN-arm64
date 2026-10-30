#!/usr/bin/env python3
"""Reliable per-pixel BRGray=OFF ink from wide bars, gray ON vs OFF.

Bars narrower than a few dither periods make the ink fit ambiguous (several
ink values reproduce a short window exactly).  This tool puts at most 12
probes per page so each bar spans many periods, recovers the ink of all four
planes, and prints it (0 = full ink) next to the profile and cmyk grids' ink.

Usage: graytol_wide.py <name> <probefile>
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
MAX_BARS = 12


def build_ppm(colors):
    step = SW // len(colors)
    row = bytearray()
    for c in colors:
        row += bytes(c) * step
    row += bytes(colors[-1]) * (SW - len(row) // 3)
    return b"P6\n%d %d\n255\n" % (SW, HEIGHT) + bytes(row) * HEIGHT


def ink_of(colors, table):
    row = np.array(colors, dtype=np.uint8).reshape(-1)
    k, c, m, y = color_lut.rgb_to_cmyk_lut_arr(row, len(colors), table)
    return 255 - np.stack([k, c, m, y], axis=1)


def measure(name, colors, tables):
    step = SW // len(colors)
    m = {}
    e = {}
    for p in PLANES:
        obs = rows(name, p)
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
    return m, e


def main() -> int:
    name = sys.argv[1]
    colors = []
    for line in Path(sys.argv[2]).read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            colors.append(tuple(int(x) for x in line.split()))
    assert len(colors) <= MAX_BARS, f"too many bars ({len(colors)}), keep <= {MAX_BARS} for a reliable fit"
    tables = dither.load_dither_tables(str(LUT_DIR), fine=False, toner_save=False)
    prof = color_lut.ColorTable("rgb", improve_gray=True, gray_replace=False)
    cmykg = color_lut.ColorTable("cmyk")
    P = ink_of(colors, prof)
    G = ink_of(colors, cmykg)

    ppm = Path(f"/tmp/{name}.ppm")
    ppm.write_bytes(build_ppm(colors))
    res = {}
    for g in ("ON", "OFF"):
        dst = Path(f"/tmp/{name}_{g}.xl2hb")
        subprocess.run([sys.executable, str(HERE / "oracle_run.py"), str(ppm), str(dst),
                        "--matching", "Normal", "--gray", g], check=True, capture_output=True)
        (FIX / f"{name}_{g}.xl2hb").write_bytes(dst.read_bytes())
        res[g] = measure(f"{name}_{g}", colors, tables)

    print(f"# {name}  bars={len(colors)}")
    for bi, c in enumerate(colors):
        common = [p for p in PLANES if p in res["ON"][0] and p in res["OFF"][0]]
        on = np.array([int(res["ON"][0][p][bi]) for p in common])
        off = np.array([int(res["OFF"][0][p][bi]) for p in common])
        errs = [int(res["OFF"][1][p][bi]) for p in common]
        idx = [PLANES.index(p) for p in common]
        dP = int(np.abs(off - P[bi][idx]).sum())
        dG = int(np.abs(off - G[bi][idx]).sum())
        tag = "cmyk" if dG < dP else ("prof" if dP < dG else "=")
        print(f"{str(c):>16} d={max(c)-min(c):3d} | ON {on.tolist()} OFF {off.tolist()} err={errs} | "
              f"prof {P[bi][idx].tolist()} cmyk {G[bi][idx].tolist()} | dP={dP:3d} dG={dG:3d} {tag}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
