#!/usr/bin/env python3
"""Measure the oracle's ink level for every bar of a tone ramp.

A ramp page is constant along y and stepped along x, so each plane's rows
repeat with the dither table's height and each bar is a column window.  For
every bar the same bit-exact fit used by `level_compare.py` recovers the ink
level: the threshold matrix is tiled to the window and compared against the
observed bits for all 256 levels, the best match wins.

Usage: ramp_measure.py <axis> [--bars N]
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))
sys.path.insert(0, str(HERE.parent / "hl3040cn" / "src"))

import dither  # noqa: E402
import pclxl  # noqa: E402
import rle_decode  # noqa: E402
from band import decode_blocks  # noqa: E402

FIX = Path("/mnt/ssd/bprobe")
LUT_DIR = HERE.parent / "hl3040cn" / "src" / "lut"
WIDTH = 5120
LINE_BYTES = WIDTH // 8
# Source pages are fed at the paper's real width; the filter pads to WIDTH.
SRC_WIDTH = 5100
DECODERS = {10: rle_decode.decode_10bit, 12: rle_decode.decode_12bit}


def plane_cycle(name: str, plane: str, want: int) -> np.ndarray | None:
    """First `want` decoded scanlines of the plane's first block as bool rows.

    The first block always starts at line 0, so the dither phase inside it is
    the phase from the top of the page; later blocks repeat rows already
    covered and would corrupt the phase, hence only the first block is used.
    """
    for b in decode_blocks(pclxl.parse((FIX / f"{name}.xl2hb").read_bytes())):
        if b.plane_name != plane or not b.entries:
            continue
        dec = DECODERS.get(b.header.comp_size)
        if dec is None:
            continue
        rows = [
            np.unpackbits(np.frombuffer(dec(e, LINE_BYTES), np.uint8))[:WIDTH].astype(bool)
            for e in b.entries
        ]
        return np.stack(rows)
    return None


def solve_window(obs: np.ndarray, table, x0: int, x1: int, phase: int) -> tuple[int, int]:
    """Best (ink, differing bits) for a column window over the table cycle.

    The threshold row used for image line i is (phase + i) mod table.height,
    matching how the dither walks the matrix down the page.  The window is
    trimmed to a whole number of table periods so the coverage is exact and
    the level estimate is not biased by a partial period.
    """
    span = x1 - x0
    period = table.width
    use = (span // period) * period or span
    x1 = x0 + use
    w = x1 - x0
    reps = w // period + 2
    tiled = np.tile(table.threshold_matrix, (1, reps))[:, x0 % period : x0 % period + w]
    h = min(obs.shape[0], table.height)
    th = np.roll(tiled, -phase, axis=0)[:h]
    obs_w = obs[:h, x0:x1]
    levels = np.arange(256, dtype=np.int32)[:, None, None]
    dots = (255 - levels) > th[None, :, :]
    err = np.count_nonzero(dots ^ obs_w[None, :, :], axis=(1, 2))
    i = int(np.argmin(err))
    return 255 - i, int(err[i])


def find_phase(obs: np.ndarray, table, x0: int, x1: int) -> int:
    """The phase that best explains one window over the whole table cycle."""
    best = (10**9, 0)
    for ph in range(table.height):
        _, err = solve_window(obs, table, x0, x1, ph)
        if err < best[0]:
            best = (err, ph)
    return best[1]


def main() -> int:
    """Print the measured ink per bar and plane for a ramp fixture."""
    axis = sys.argv[1] if len(sys.argv) > 1 else "r"
    bars = 64
    if "--bars" in sys.argv:
        bars = int(sys.argv[sys.argv.index("--bars") + 1])
    nodes = "--nodes" in sys.argv
    port = "--port" in sys.argv
    tables = dither.load_dither_tables(str(LUT_DIR), fine=False, toner_save=False)
    suffix = "_port" if port else ""
    if nodes:
        values = [i * 16 for i in range(16)] + [255]
        name = f"ramp_{axis}nodes{suffix}"
        step = SRC_WIDTH // len(values)
        bars = len(values)
    else:
        values = [round(i * 255 / (bars - 1)) for i in range(bars)]
        name = f"ramp_{axis}{suffix}"
        step = SRC_WIDTH // bars
    cycles: dict[str, np.ndarray] = {}
    for p in ("K", "C", "M", "Y"):
        cyc = plane_cycle(name, p, tables[p].height)
        if cyc is not None:
            cycles[p] = cyc
    planes = list(cycles)
    # One phase per plane, solved on a mid bar where the level is well inside
    # the range, then reused for every bar (the phase is a page property).
    mid = bars // 2
    phases = {p: find_phase(cycles[p], tables[p], mid * step, (mid + 1) * step) for p in planes}
    print(f"# ramp={name} bars={bars} planes={planes} phase={phases}")
    print(f"{'bar':>3s} {'val':>3s} " + " ".join(f"{p+'_tinte':>8s}" for p in planes)
          + "  " + " ".join(f"{p+'_fehl':>8s}" for p in planes))
    worst = dict.fromkeys(planes, 0)
    for bi in range(bars):
        x0, x1 = bi * step, (bi + 1) * step
        val = values[bi]
        inks, errs = [], []
        for p in planes:
            ink, err = solve_window(cycles[p], tables[p], x0, x1, phases[p])
            inks.append(f"{ink:8d}")
            errs.append(f"{err:8d}")
            worst[p] = max(worst[p], err)
        print(f"{bi:3d} {val:3d} " + " ".join(inks) + "  " + " ".join(errs))
    print(f"# worst fit error per plane: {worst}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
