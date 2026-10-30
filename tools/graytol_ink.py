#!/usr/bin/env python3
"""Oracle ink (per plane) for solid colours, and the (pixel, grid) that reproduces it."""
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
from graytol_fullink import plane_bitmap, solid_ink  # noqa: E402

FIX = Path("/mnt/ssd/bprobe")
LUT_DIR = HERE.parent / "hl3040cn" / "src" / "lut"
SW, HEIGHT = 5100, 6564
PLANES = ("K", "C", "M", "Y")


def ppm_of(c):
    return b"P6\n%d %d\n255\n" % (SW, HEIGHT) + bytes(c) * SW * HEIGHT


def main() -> int:
    matching = sys.argv[sys.argv.index("--matching") + 1] if "--matching" in sys.argv else "Normal"
    gray = sys.argv[sys.argv.index("--gray") + 1] if "--gray" in sys.argv else "OFF"
    box = int(sys.argv[sys.argv.index("--box") + 1]) if "--box" in sys.argv else 40
    colors = []
    for line in Path(sys.argv[1]).read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            colors.append(tuple(int(x) for x in line.split()))
    tables = dither.load_dither_tables(str(LUT_DIR), fine=False, toner_save=False)
    grids = [color_lut.ColorTable(p, ig, v) for p in ("rgb", "srgb", "cmyk")
             for ig in (False, True) for v in ("default", "density2", "glossy")]
    cand = [(v, v, v) for v in range(256)]
    cand += [(r, g, b) for r in range(box + 1) for g in range(box + 1) for b in range(box + 1)]
    px = np.array(cand, dtype=np.uint8)
    grid_inks = {}
    for g in grids:
        k, c, m, y = color_lut.rgb_to_cmyk_lut_arr(px.reshape(-1), len(cand), g)
        grid_inks[g.name] = np.stack([k, c, m, y], axis=1).astype(np.int16)
    print(f"# matching={matching} gray={gray} box={box} cands={len(cand)}")
    for ci, col in enumerate(colors):
        p = FIX / f"ink{ci}.ppm"
        p.write_bytes(ppm_of(col))
        subprocess.run([sys.executable, str(HERE / "oracle_run.py"), str(p), f"/tmp/ink{ci}.xl2hb",
                        "--matching", matching, "--gray", gray], check=True, capture_output=True)
        (FIX / f"ink{ci}.xl2hb").write_bytes(Path(f"/tmp/ink{ci}.xl2hb").read_bytes())
        want = []
        for pl in PLANES:
            obs = plane_bitmap(f"ink{ci}", pl)
            if obs is None:
                want.append(None)
            else:
                ink, err = solid_ink(obs, tables[pl])
                want.append(ink if err == 0 else f"?{ink}(e{err})")
        hits = []
        if all(isinstance(w, int) for w in want):
            tgt = np.array(want, dtype=np.int16)
            for name, inks in grid_inks.items():
                eq = np.all(inks == tgt[None, :], axis=1)
                for i in np.flatnonzero(eq):
                    hits.append((cand[i], name))
        print(f"{str(col):>16} ink(KCMY)={want} -> {hits[:6] if hits else 'NONE'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
