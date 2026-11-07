#!/usr/bin/env python3
"""Benchmark the native kernels against their pure-Python references.

The kernel port is proven *correct* byte for byte (test_native_kernels_equiv,
test_fine_fast_equiv).  This script answers the other question -- how much the
native path actually buys -- with numbers instead of a guess.

Every case is driven with *synthetic* inputs built to the driver's real
geometry (A4 at 600 dpi: 4958 px wide, 620 bytes per 1bpp line, 128-row bands),
so the script runs on a fresh checkout without Brother's proprietary blobs.
The pure-Python side is the same reference each equivalence test uses, so a
timing difference cannot come from the two sides doing different work.

Timing is `perf_counter`, one warm-up run, then the median of N runs (CI timing
is noisy; a mean would be dragged around by a single outlier).  Sizes are kept
so the slowest Python case stays well under a second.

Usage:
    python3 tools/bench_kernels.py [--json]
"""

from __future__ import annotations

import argparse
import json
import random
import statistics
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "hl3040cn" / "src"))

try:
    import _band_fast
    import _color_fast
    import _dither_fast
    import _fine_fast
    import _rle_fast
except ImportError as exc:  # pragma: no cover - the pure-Python CI
    print(f"native kernels not importable ({exc}); nothing to benchmark")
    raise SystemExit(0)

import color_lut  # noqa: E402
import fine_encoder  # noqa: E402
import rle  # noqa: E402
from test_native_kernels_equiv import (  # noqa: E402
    _GRID_ENTRIES,
    _LUT_SIZE,
    _random_weights,
    _ref_dither_1bpp,
    _ref_dither_4bpp,
    _ref_encode_sw_rle,
    _ref_gather_planes,
    _ref_interp_planes,
    _ref_render_band,
)
from xl2hb import PAPER_SIZES  # noqa: E402

A4_W, _A4_H = PAPER_SIZES["A4"]
BPL = (A4_W + 7) // 8  # bytes per 1bpp scanline, 620 for A4
SEED = 20261101


def _median_time(fn, reps: int) -> float:
    fn()  # warm-up: first call pays import/JIT-style costs
    samples = []
    for _ in range(reps):
        t0 = time.perf_counter()
        fn()
        samples.append(time.perf_counter() - t0)
    return statistics.median(samples)


def _inputs():
    """Deterministic synthetic inputs at the driver's real geometry."""
    rng = random.Random(SEED)
    row = np.frombuffer(rng.randbytes(A4_W), dtype=np.uint8)
    thr = np.frombuffer(rng.randbytes(A4_W), dtype=np.uint8)
    rgb = np.frombuffer(rng.randbytes(A4_W * 3), dtype=np.uint8)
    lut = np.frombuffer(rng.randbytes(_LUT_SIZE), dtype=np.uint8)

    height, wb = 80, BPL
    patterns = np.frombuffer(rng.randbytes(256 * height * wb), dtype=np.uint8)
    pat_args = (patterns, 256, height * wb, (37 % height) * wb, wb, A4_W)

    grid = np.frombuffer(rng.randbytes(_GRID_ENTRIES * 4), dtype=np.uint8).astype(np.int32).reshape(_GRID_ENTRIES, 4)
    weights = _random_weights(rng)
    black = color_lut._K_PRESET.copy()

    line = rng.randbytes(BPL)
    fine_line = rng.randbytes(BPL * 4)
    return row, thr, rgb, lut, patterns, pat_args, grid, weights, black, line, fine_line


def _cases():
    row, thr, rgb, lut, patterns, pat_args, grid, weights, black, line, fine_line = _inputs()
    planes = [np.empty(A4_W, dtype=np.uint8) for _ in range(4)]

    # Band case: small enough that the per-line Python loop stays fast.
    band_rng = random.Random(SEED + 1)
    n, bw = 16, 256
    band_rows = np.frombuffer(band_rng.randbytes(n * bw * 3), dtype=np.uint8).reshape(n, bw * 3)
    skip = np.zeros(n, dtype=np.uint8)
    thr_band = tuple(
        np.frombuffer(band_rng.randbytes(h * bw), dtype=np.uint8).reshape(h, bw) for h in (80, 80, 24, 80)
    )
    colour = (np.zeros(0, dtype=np.uint8), grid.reshape(-1), weights.reshape(-1), black)
    lengths = np.zeros((n, 4), dtype=np.int32)

    def native_band():
        return _band_fast.render_band(band_rows, skip, bw, 0, bw, *colour, *thr_band, lengths)

    def python_band():
        return _ref_render_band(band_rows, skip, bw, 0, bw, colour[0], grid, weights, black, thr_band)

    stage1 = fine_encoder.compress_rle_preencode_py(fine_line)

    return [
        ("_dither_fast.dither_row_1bpp", lambda: _dither_fast.dither_row_1bpp(row, thr, A4_W),
         lambda: _ref_dither_1bpp(row, thr, A4_W), 200),
        ("_dither_fast.dither_row_4bpp_pattern", lambda: _dither_fast.dither_row_4bpp_pattern(row, *pat_args),
         lambda: _ref_dither_4bpp(row, *pat_args), 200),
        ("_color_fast.gather_kcmy", lambda: _color_fast.gather_kcmy(rgb, A4_W, lut, *planes),
         lambda: _ref_gather_planes(rgb, A4_W, lut), 50),
        ("_color_fast.interp_kcmy",
         lambda: _color_fast.interp_kcmy(rgb, A4_W, grid.reshape(-1), weights.reshape(-1), black, *planes),
         lambda: _ref_interp_planes(rgb, A4_W, grid, weights), 20),
        ("_rle_fast.group_bits", lambda: _rle_fast.group_bits(line, 12),
         lambda: rle.group_bits_py(line, 12), 500),
        ("_rle_fast.pack_groups", lambda: _rle_fast.pack_groups(list(_rle_fast.group_bits(line, 12)), 12),
         lambda: rle.pack_groups_py(rle.group_bits_py(line, 12), 12), 200),
        ("_rle_fast.encode_sw_rle", lambda: _rle_fast.encode_sw_rle(line, 12),
         lambda: _ref_encode_sw_rle(line, 12), 100),
        ("_fine_fast.compress_rle_preencode", lambda: _fine_fast.compress_rle_preencode(fine_line),
         lambda: fine_encoder.compress_rle_preencode_py(fine_line), 20),
        ("_fine_fast.compress_pattern_encode", lambda: _fine_fast.compress_pattern_encode(stage1),
         lambda: fine_encoder.compress_pattern_encode_py(stage1), 20),
        ("_band_fast.render_band", native_band, python_band, 20),
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="print the raw numbers as JSON")
    args = parser.parse_args()

    rows = []
    for name, native, python, reps in _cases():
        t_native = _median_time(native, reps)
        t_python = _median_time(python, reps)
        rows.append(
            {
                "kernel": name,
                "python_ms": round(t_python * 1e3, 4),
                "native_ms": round(t_native * 1e3, 4),
                "speedup": round(t_python / t_native, 1) if t_native else float("inf"),
            }
        )

    if args.json:
        print(json.dumps(rows, indent=2))
        return 0

    print(f"# Kernel benchmark (A4 @600 dpi, {A4_W} px, {BPL} B/line)\n")
    print("| kernel | python (ms) | native (ms) | speedup |")
    print("|---|---:|---:|---:|")
    for r in rows:
        print(f"| `{r['kernel']}` | {r['python_ms']:.3f} | {r['native_ms']:.3f} | {r['speedup']}x |")

    slower = [r["kernel"] for r in rows if r["speedup"] < 1.0]
    if slower:
        print("\nWARNING: the native kernel is slower than Python for: " + ", ".join(slower))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
