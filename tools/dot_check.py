#!/usr/bin/env python3
"""The decisive test: does the model reproduce the oracle's DOTS, not just levels?

`ramp_measure.py` recovers one ink level per bar by best-fit, but a level is
only observable through its dot pattern: several adjacent levels can give the
identical pattern, so a +/-1 "level error" may be a measurement artefact.  For
every bar this tool (a) finds the phase as `ramp_measure` does, (b) lists the
levels whose rendered pattern matches the oracle exactly, and (c) checks
whether the model's predicted level is one of them.  If it is for every bar,
the colour transformation reproduces the oracle bit-exactly.

Usage: dot_check.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "src"))
sys.path.insert(0, str(HERE.parent / "hl3040cn" / "src"))

import dither  # noqa: E402
from exact_interp import interp_exact, load_grid, load_weights  # noqa: E402
from ramp_measure import find_phase, plane_cycle  # noqa: E402

SRC_WIDTH = 5100
VALUES = [round(i * 255 / 59) for i in range(60)]
PLANES = {"R": ["K", "M", "Y"], "G": ["K", "Y"], "B": ["K", "M", "Y"]}
COORD = {"R": 0, "G": 1, "B": 2}
COL = {"K": 3, "C": 0, "M": 1, "Y": 2}
ORDER = (2, 1, 0)  # best weight-table axis order from exact_interp.py


def zero_levels(obs: np.ndarray, table, x0: int, x1: int, phase: int) -> list[int]:
    """All levels whose tiled pattern matches the window exactly."""
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
    err = np.count_nonzero(((255 - levels) > th[None]) ^ obs_w[None], axis=(1, 2))
    return (255 - np.nonzero(err == 0)[0]).tolist()


def main() -> int:
    """Check each bar: is the model's level among the pattern-exact levels?"""
    grid = load_grid()
    weights = load_weights()
    tables = dither.load_dither_tables(str(HERE.parent / "hl3040cn" / "src" / "lut"), fine=False, toner_save=False)
    step = SRC_WIDTH // 60
    bad = 0
    for axis, planes in PLANES.items():
        rgb = np.array([[v if j == COORD[axis] else 0 for j in range(3)] for v in VALUES])
        ink = interp_exact(grid, weights, rgb, ORDER)  # integer ink C,M,Y,K
        print(f"=== {axis} ramp ===")
        for plane in planes:
            obs = plane_cycle(f"ramp_{axis.lower()}60", plane, 10**6)
            table = tables[plane]
            phase = find_phase(obs, table, 30 * step, 31 * step)
            model = ink[:, COL[plane]]  # ink level (0=no ink, 255=full)
            misses = []
            for bi in range(60):
                zs = zero_levels(obs, table, bi * step, (bi + 1) * step, phase)
                if int(model[bi]) not in zs:
                    misses.append((bi, int(model[bi]), (min(zs), max(zs)) if zs else None))
            print(f"  {plane:2s} phase={phase} bars={len(VALUES)} misses={len(misses)}")
            for bi, m, rng in misses[:8]:
                print(f"      bar {bi:2d} val={VALUES[bi]:3d} model={m:3d} exact-range={rng}")
            bad += len(misses)
    print(f"\nGESAMT bars where the model level is not pattern-exact: {bad}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
