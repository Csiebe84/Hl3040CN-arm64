#!/usr/bin/env python3
"""Performance benchmark for the native HL-3040CN raster kernels.

Why
---
The five Cython kernels (``_dither_fast``, ``_color_fast``, ``_rle_fast``,
``_band_fast``, ``_fine_fast``) were replaced by the Rust extension
``_hl3040cn_native``.  Correctness is pinned byte-for-byte by
``test_native_kernels_equiv.py`` and ``test_fine_fast_equiv.py``, but the
repository carried no performance number at all.  This tool measures each
kernel against its pure-Python reference and prints the speedup.

What
----
Every case drives the *active* native implementation and the *pure-Python*
reference on the same synthetic input, built the way the equivalence tests
build it -- random bytes, a random inverse LUT, a random 17x17x17 grid -- so no
Brother blob (``src/lut/``, ``src/color_data/``) is read and the tool runs in
the CI ``rust-kernels`` job on a fresh checkout.  The references are imported
from ``test_native_kernels_equiv`` so the two sides cannot drift apart.

Sizes come from the real geometry rather than guesswork: the A4 source width
from ``xl2hb.get_image_dimensions``, the bytes per line the pipeline derives
from it, the Fine-mode line, ``pipeline._BAND_ROWS`` scanlines per band, and
the real BRCD Fine-pattern geometry.  The pure-Python side is the slow one, so
each case is sized to keep a single reference run in the millisecond range.

Timing is ``time.perf_counter``: a couple of warmup runs, then a fixed number
of repetitions, reported as the median (CI timing is noisy and a mean would be
dragged around by a single stall).

The tool is not a test: it always exits 0.  It warns on stderr when a native
kernel comes out slower than Python, which would mean a regression.

Usage
-----
    python3 tools/bench_kernels.py            # markdown table
    python3 tools/bench_kernels.py --json     # raw numbers
"""

from __future__ import annotations

import argparse
import json
import random
import statistics
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import numpy as np

# The pure-Python modules live next to the kernels in ``hl3040cn/src``.  Append
# rather than prepend so an installed driver (``PYTHONPATH=/usr/local/lib/brhl3040cn``)
# keeps precedence for the ``_*_fast`` extensions; on a fresh checkout the same
# directory supplies the modules and the staged ``.so``/shims.
sys.path.append(str(Path(__file__).resolve().parent.parent / "hl3040cn" / "src"))

import color_lut  # noqa: E402
import pipeline  # noqa: E402
import rle  # noqa: E402
import xl2hb  # noqa: E402

_NATIVE_MODULES = ("_rle_fast", "_dither_fast", "_color_fast", "_band_fast", "_fine_fast")

SEED = 20261101
_GRID_ENTRIES = 4913  # 17**3, the colour interpolation grid size

# Real BRCD Fine-pattern geometry of the K/Y tables (``capt-k_cache08.bin``):
# 96x12 pixels -> 12 bytes per screen row, 144 bytes per ink level.
_PAT_WIDTH, _PAT_HEIGHT = 96, 12
_PAT_ROW_BYTES = (_PAT_WIDTH * _PAT_HEIGHT + 7) // 8
_PAT_WB = _PAT_WIDTH // 8


@dataclass
class _Case:
    """One function pair to measure on shared, pre-built input."""

    kernel: str
    python: Callable[[], object]
    native: Callable[[], object]
    repeats: int = 7


@dataclass
class _Result:
    """Median timings of one case, in milliseconds."""

    kernel: str
    python_ms: float
    native_ms: float

    @property
    def speedup(self) -> float:
        """Python time divided by native time."""
        return self.python_ms / self.native_ms if self.native_ms > 0 else float("inf")


def _median_seconds(fn: Callable[[], object], warmup: int, repeats: int) -> float:
    """Median wall time of `fn` over `repeats` runs after `warmup` discards."""
    for _ in range(warmup):
        fn()
    samples = []
    for _ in range(repeats):
        start = time.perf_counter()
        fn()
        samples.append(time.perf_counter() - start)
    return statistics.median(samples)


def _geometry() -> dict[str, int]:
    """Real A4 raster geometry the pipeline works with at 600 dpi."""
    sw, _ = xl2hb.get_image_dimensions("A4")
    fsw, _ = xl2hb.get_image_dimensions_fine("A4")
    return {
        "source_width": sw,
        "bpl": (sw + 7) // 8,
        "fine_bpl": (fsw + 1) // 2,
        "band_rows": pipeline._BAND_ROWS,
    }


def _random_grid(rng: random.Random, entries: int = _GRID_ENTRIES) -> np.ndarray:
    """A synthetic (entries, 4) int32 colour grid of random ink amounts."""
    return np.frombuffer(rng.randbytes(entries * 4), dtype=np.uint8).astype(np.int32).reshape(entries, 4)


def _pat_offset(row: int) -> int:
    """BRCD pattern byte offset for scanline `row`, wrapping at the table height."""
    return (row % _PAT_HEIGHT) * _PAT_WB


def _build_cases(native: dict[str, object]) -> list[_Case]:
    """Assemble the measurable cases for the native modules that imported."""
    # Imported here, not at module level: `test_native_kernels_equiv` raises
    # `unittest.SkipTest` at import time when no kernel is importable, which is
    # exactly the skip path this tool must survive.
    from test_native_kernels_equiv import (
        _LUT_SIZE,
        _random_weights,
        _ref_dither_1bpp,
        _ref_dither_4bpp,
        _ref_encode_sw_rle,
        _ref_gather_planes,
        _ref_interp_planes,
        _ref_render_band,
    )

    rng = random.Random(SEED)
    geom = _geometry()
    sw, bpl, band_rows, fine_bpl = (
        geom["source_width"],
        geom["bpl"],
        geom["band_rows"],
        geom["fine_bpl"],
    )
    cases: list[_Case] = []

    rle_native = native.get("_rle_fast")
    if rle_native is not None:
        band_bytes = rng.randbytes(bpl * band_rows)
        groups_band = rle.group_bits_py(band_bytes, 12)
        k_line = rng.randbytes(bpl)
        cases += [
            _Case(
                "_rle_fast.group_bits",
                lambda: rle.group_bits_py(band_bytes, 12),
                lambda: rle_native.group_bits(band_bytes, 12),
            ),
            _Case(
                "_rle_fast.pack_groups",
                lambda: rle.pack_groups_py(groups_band, 12),
                lambda: rle_native.pack_groups(groups_band, 12),
            ),
            _Case(
                "_rle_fast.encode_sw_rle",
                lambda: _ref_encode_sw_rle(k_line, 12),
                lambda: rle_native.encode_sw_rle(k_line, 12),
            ),
        ]

    dither_native = native.get("_dither_fast")
    if dither_native is not None:
        dith_rows = np.frombuffer(rng.randbytes(band_rows * sw), dtype=np.uint8).reshape(band_rows, sw)
        thr_rows = np.frombuffer(rng.randbytes(band_rows * sw), dtype=np.uint8).reshape(band_rows, sw)
        cases.append(
            _Case(
                "_dither_fast.dither_row_1bpp",
                lambda: [_ref_dither_1bpp(dith_rows[i], thr_rows[i], sw) for i in range(band_rows)],
                lambda: [dither_native.dither_row_1bpp(dith_rows[i], thr_rows[i], sw) for i in range(band_rows)],
            )
        )

        pats = np.frombuffer(rng.randbytes(256 * _PAT_ROW_BYTES), dtype=np.uint8).reshape(256, _PAT_ROW_BYTES)
        pats_flat = pats.reshape(-1)
        fine_rows = np.frombuffer(rng.randbytes(band_rows * sw), dtype=np.uint8).reshape(band_rows, sw)

        def python_4bpp() -> list[bytes]:
            return [
                _ref_dither_4bpp(fine_rows[i], pats, 256, _PAT_ROW_BYTES, _pat_offset(i), _PAT_WB, sw)
                for i in range(band_rows)
            ]

        def native_4bpp() -> list[bytes]:
            return [
                dither_native.dither_row_4bpp_pattern(
                    fine_rows[i], pats_flat, 256, _PAT_ROW_BYTES, _pat_offset(i), _PAT_WB, sw
                )
                for i in range(band_rows)
            ]

        cases.append(_Case("_dither_fast.dither_row_4bpp_pattern", python_4bpp, native_4bpp))

    color_native = native.get("_color_fast")
    if color_native is not None:
        rgb_row = np.frombuffer(rng.randbytes(sw * 3), dtype=np.uint8)
        inv_lut = np.frombuffer(rng.randbytes(_LUT_SIZE), dtype=np.uint8)
        planes = [np.empty(sw, dtype=np.uint8) for _ in range(4)]
        grid = _random_grid(rng)
        weights = _random_weights(rng)
        black = color_lut._K_PRESET.copy()
        cases += [
            _Case(
                "_color_fast.gather_kcmy",
                lambda: _ref_gather_planes(rgb_row, sw, inv_lut),
                lambda: color_native.gather_kcmy(rgb_row, sw, inv_lut, *planes),
            ),
            _Case(
                "_color_fast.interp_kcmy",
                lambda: _ref_interp_planes(rgb_row, sw, grid, weights),
                lambda: color_native.interp_kcmy(
                    rgb_row, sw, grid.reshape(-1), weights.reshape(-1), black, *planes
                ),
            ),
        ]

    band_native = native.get("_band_fast")
    if band_native is not None:
        n = 8  # small synthetic band, as the per-line Python reference is slow
        rows = np.frombuffer(rng.randbytes(n * sw * 3), dtype=np.uint8).reshape(n, sw * 3)
        skip = np.zeros(n, dtype=np.uint8)
        skip[n // 2] = 1
        thr = tuple(
            np.ascontiguousarray(np.frombuffer(rng.randbytes(h * sw), dtype=np.uint8).reshape(h, sw))
            for h in (80, 80, 24, 80)  # real BRCD threshold-matrix heights
        )
        grid = _random_grid(rng)
        weights = _random_weights(rng)
        black = color_lut._K_PRESET.copy()
        lengths = np.zeros((n, 4), dtype=np.int32)
        empty_u8 = np.empty(0, dtype=np.uint8)
        colour = (empty_u8, grid.reshape(-1), weights.reshape(-1), black)
        cases.append(
            _Case(
                "_band_fast.render_band",
                lambda: _ref_render_band(rows, skip, sw, 0, sw, empty_u8, grid, weights, black, thr),
                lambda: band_native.render_band(rows, skip, sw, 0, sw, *colour, *thr, lengths),
                repeats=5,
            )
        )

    fine_native = native.get("_fine_fast")
    if fine_native is not None:
        import fine_encoder

        fine_line = rng.randbytes(fine_bpl)
        stage1 = fine_encoder.compress_rle_preencode_py(fine_line)
        cases += [
            _Case(
                "_fine_fast.compress_rle_preencode",
                lambda: fine_encoder.compress_rle_preencode_py(fine_line),
                lambda: fine_native.compress_rle_preencode(fine_line),
            ),
            _Case(
                "_fine_fast.compress_pattern_encode",
                lambda: fine_encoder.compress_pattern_encode_py(stage1),
                lambda: fine_native.compress_pattern_encode(stage1),
            ),
        ]

    return cases


def _benchmark(cases: list[_Case], warmup: int) -> list[_Result]:
    """Time the Python and native side of every case."""
    results = []
    for case in cases:
        python_s = _median_seconds(case.python, warmup, case.repeats)
        native_s = _median_seconds(case.native, warmup, case.repeats)
        results.append(_Result(case.kernel, python_s * 1e3, native_s * 1e3))
    return results


def _print_markdown(results: list[_Result], native_names: list[str], warmup: int) -> None:
    """Print the results as a markdown table."""
    print(f"Native kernels: {', '.join(native_names)}")
    print(f"warmup={warmup} runs, median of per-case repetitions")
    print()
    print("| kernel | python (ms) | native (ms) | speedup |")
    print("| --- | ---: | ---: | ---: |")
    for r in results:
        print(f"| {r.kernel} | {r.python_ms:.3f} | {r.native_ms:.3f} | {r.speedup:.1f}x |")


def _print_json(results: list[_Result], geometry: dict[str, int], warmup: int) -> None:
    """Print the raw numbers as JSON."""
    payload = {
        "geometry": geometry,
        "warmup": warmup,
        "results": [
            {
                "kernel": r.kernel,
                "python_ms": r.python_ms,
                "native_ms": r.native_ms,
                "speedup": r.speedup,
            }
            for r in results
        ],
    }
    print(json.dumps(payload, indent=2))


def _warn_regressions(results: list[_Result]) -> None:
    """A native kernel slower than its Python reference is a regression, not a win."""
    for r in results:
        if r.native_ms > r.python_ms:
            print(
                f"WARNING: {r.kernel} native is slower than Python "
                f"({r.native_ms:.3f} ms vs {r.python_ms:.3f} ms)",
                file=sys.stderr,
            )


def main(argv: list[str] | None = None) -> int:
    """Run the benchmark; always returns 0 (it is not a test)."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--json", action="store_true", help="emit raw numbers as JSON instead of the table")
    parser.add_argument("--warmup", type=int, default=2, help="warmup runs discarded before timing (default: 2)")
    args = parser.parse_args(argv)

    native: dict[str, object] = {}
    for name in _NATIVE_MODULES:
        try:
            native[name] = __import__(name)
        except Exception:  # noqa: BLE001 - a missing or broken .so just skips that kernel
            native[name] = None

    if not any(native.values()):
        print("no native kernels importable; skipping benchmark (build the Rust extension first)")
        return 0

    cases = _build_cases(native)
    results = _benchmark(cases, args.warmup)
    if args.json:
        _print_json(results, _geometry(), args.warmup)
    else:
        _print_markdown(results, [name for name, mod in native.items() if mod is not None], args.warmup)
    _warn_regressions(results)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
