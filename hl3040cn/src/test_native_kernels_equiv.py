#!/usr/bin/env python3
"""Byte-exact equivalence of the Rust kernels against the pure-Python references.

Why this module exists
----------------------
The Cython kernels ``_dither_fast``, ``_color_fast``, ``_rle_fast`` and
``_band_fast`` were replaced by the Rust extension ``_hl3040cn_native`` (the
old module names are kept as re-export shims in ``hl3040cn/rust/shims/``).  The
pre-existing tests that cover dither, colour and banding read Brother's
proprietary blobs ``src/lut/`` (BRCD dither tables) and ``src/color_data/``
(colour grids).  Those blobs are not in the repository (``.gitignore``), so on a
fresh checkout -- i.e. in the GitHub CI ``tests`` job -- those tests *skip* and
the native path for these four kernels is left unverified.  Only ``_fine_fast``
already has a blob-free golden corpus (``test_fine_fast_equiv.py``).

This module drives every replaced kernel with *synthetic* inputs against the
pure-Python reference, so it runs without any Brother blob and still covers the
native path.  It compares byte for byte:

* ``_dither_fast.dither_row_1bpp``          vs the ``255 - row > thr`` pack
* ``_dither_fast.dither_row_4bpp_pattern``  vs the numpy BRCD pattern gather
* ``_color_fast.gather_kcmy``               vs the numpy inverse-LUT gather
* ``_color_fast.interp_kcmy``               vs ``color_lut._rgb_to_cmyk_interp_arr``
* ``_rle_fast.group_bits`` / ``pack_groups`` vs ``rle.group_bits_py`` / ``pack_groups_py``
* ``_rle_fast.encode_sw_rle``               vs ``rle.sw_rle_encode`` + ``finalize_compressed``
* ``_band_fast.render_band``                vs the per-line loop from ``pipeline._render_page``

The reference for ``gather_kcmy`` is the numpy gather branch of
``color_lut._gather_planes``: ``_gather_planes`` itself dispatches to the kernel
when it is importable, so calling it would compare the kernel with itself.  The
reference for ``interp_kcmy`` patches ``color_lut._load_data`` to hand the pure
Python path the same synthetic grid and weights the kernel is given, so no blob
is read.

Limitations
-----------
``render_band`` is covered in grid-interpolation mode and in inverse-LUT mode
(with a synthetic LUT).  The RLE stage inside ``render_band`` is the *same*
native code as ``encode_sw_rle`` (exercised directly above), so this module
verifies the band's colour, dither and indexing logic and shares the encoder
check with ``EncodeSwRleEquivTest`` rather than duplicating it.  Fine mode is
out of scope (it is not a ``render_band`` mode and already has a golden corpus).

The whole module skips when the native kernels are not importable, so the pure
Python CI workflow stays green while the native job (``rust-kernels.yml``) runs
it for real.
"""

from __future__ import annotations

import functools
import random
import unittest
from unittest import mock

import numpy as np

import color_lut
import dither
import plane_encoders
import rle

try:
    import _band_fast
    import _color_fast
    import _dither_fast
    import _rle_fast
except ImportError as exc:  # pragma: no cover - exercised by the pure-Python CI
    raise unittest.SkipTest(
        f"native kernels not importable ({exc}); build the Rust extension "
        "(hl3040cn/rust) or install the Cython modules to run this suite"
    )

SEED = 20261101
_LUT_SIZE = 256 * 256 * 256 * 4
_GRID_ENTRIES = 4913  # 17**3
_WEIGHT_ENTRIES = 17 * 289 * 9

# Per-plane encoders in plane order (K, C, M, Y), as in `pipeline._PLANE_ENCODERS`.
_ENCODERS = (
    functools.partial(plane_encoders.encode_plane, plane="K"),
    plane_encoders.encode_c_plane,
    plane_encoders.encode_m_plane_10,
    functools.partial(plane_encoders.encode_plane, plane="Y"),
)
_SW_CFG = {10: rle.CONFIG_10BIT, 12: rle.CONFIG_12BIT, 20: rle.CONFIG_20BIT}


def _rng() -> random.Random:
    """A fresh, deterministic generator so every test replays identically."""
    return random.Random(SEED)


def _u8(n: int, rng: random.Random) -> np.ndarray:
    """`n` deterministic random bytes as a contiguous uint8 array."""
    return np.frombuffer(rng.randbytes(n), dtype=np.uint8)


@functools.lru_cache(maxsize=1)
def _random_inverse_lut() -> np.ndarray:
    """A synthetic 256*256*256*4 inverse LUT (random bytes, no Brother blob)."""
    return _u8(_LUT_SIZE, _rng())


def _random_weights(rng: random.Random) -> np.ndarray:
    """Synthetic interpolation weights, 17 tables of 289 x 9 bytes.

    The first byte of each entry is the interpolation total.  It is forced
    non-zero here so the reference does not log its "zero weight" warning for
    every entry; the all-zero-total path has its own test.
    """
    weights = np.array(_u8(_WEIGHT_ENTRIES, rng).reshape(17, 289, 9))
    weights[:, :, 0] |= 1
    return weights


# ---------------------------------------------------------------------------
# Pure-Python references
# ---------------------------------------------------------------------------


def _ref_dither_1bpp(row: np.ndarray, thresholds: np.ndarray, width: int) -> bytes:
    """The non-native branch of `dither.dither_channel_1bpp_arr`."""
    ink = 255 - row[:width]
    return np.packbits(ink > thresholds[:width]).tobytes()


def _ref_dither_4bpp(
    row: np.ndarray,
    patterns: np.ndarray,
    n_ink: int,
    pattern_row_bytes: int,
    pattern_offset: int,
    wb: int,
    width: int,
) -> bytes:
    """The vector path of `dither.dither_channel_4bpp_pattern_arr`.

    `patterns` is the (n_ink, pattern_row_bytes) table; the kernel gets it
    flattened, so flatten it the same way here.
    """
    ink = np.minimum((255 - row[:width]).astype(np.int64), n_ink - 1)
    col = pattern_offset + (np.arange(width, dtype=np.int64) % wb)
    levels = patterns.reshape(-1)[ink * pattern_row_bytes + col] & 0x0F
    packed = ((levels[0::2].astype(np.uint16) << 4) | levels[1::2].astype(np.uint16)).astype(np.uint8)
    return packed.tobytes()


def _ref_gather_planes(rgb_row: np.ndarray, width: int, lut_flat: np.ndarray) -> np.ndarray:
    """The numpy branch of `color_lut._gather_planes` (K, C, M, Y rows)."""
    inv = lut_flat.reshape(-1, 4)
    rgb = np.frombuffer(rgb_row, dtype=np.uint8, count=width * 3).reshape(width, 3)
    idx = (rgb[:, 0].astype(np.uint32) << 16) | (rgb[:, 1].astype(np.uint32) << 8) | rgb[:, 2].astype(np.uint32)
    return np.ascontiguousarray(inv[idx].T)


def _ref_interp_planes(
    rgb_row: np.ndarray,
    width: int,
    grid2d: np.ndarray,
    weights3d: np.ndarray,
    table: color_lut.ColorTable = color_lut.DEFAULT_TABLE,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """`color_lut._rgb_to_cmyk_interp_arr` fed the caller's synthetic arrays.

    The kernel takes the grid and weights as arguments; the pure-Python path
    loads them from `_load_data`, so swap that out for the duration of the call
    to compare the two on identical data without touching a blob.
    """
    original = color_lut._load_data
    color_lut._load_data = lambda _table=None: (grid2d, weights3d)
    try:
        return color_lut._rgb_to_cmyk_interp_arr(rgb_row, width, table)
    finally:
        color_lut._load_data = original


def _ref_encode_sw_rle(data: bytes, bits: int) -> bytes:
    """`rle.group_bits_py` -> `rle.sw_rle_encode` -> `rle.finalize_compressed`.

    This is the pure-Python path `plane_encoders` uses without the native
    kernel: an all-zero word sequence short-circuits to empty, otherwise the
    sliding-window RLE runs and `finalize_compressed` swaps in the raw fallback
    when the compressed form would be larger.
    """
    if not data:
        return b""
    words = rle.group_bits_py(data, bits)
    if not words or not any(words):
        return b""
    return rle.finalize_compressed(rle.sw_rle_encode(words, _SW_CFG[bits]), data, bits)


def _ref_render_band(rows, skip, width, first_line, sw, lut, grid2d, weights3d, black, thr):
    """The per-line loop from `pipeline._render_page` that `render_band` replaces.

    Colour (inverse LUT or interpolated grid) -> 1bpp threshold dither -> per
    plane `encode_plane` / `encode_c_plane` / `encode_m_plane_10`.  Returns the
    concatenated plane bytes and the (n, 4) length matrix the kernel fills.
    """
    n = rows.shape[0]
    npx = min(width, sw)
    bpl = (sw + 7) // 8
    has_lut = lut.size != 0
    out = bytearray()
    lengths = np.zeros((n, 4), dtype=np.int32)
    for i in range(n):
        if skip[i]:
            continue
        line = first_line + i
        rgb_row = np.ascontiguousarray(rows[i, : npx * 3])
        if has_lut:
            planes = _ref_gather_planes(rgb_row, npx, lut)
        else:
            planes = np.stack(_ref_interp_planes(rgb_row, npx, grid2d, weights3d))
        for pid in range(4):
            trow = thr[pid][line % thr[pid].shape[0]]
            packed = np.packbits((255 - planes[pid]) > trow[:npx])
            buf = np.zeros(bpl, dtype=np.uint8)
            buf[: packed.size] = packed
            comp = _ENCODERS[pid](bytes(buf))
            lengths[i, pid] = len(comp)
            out.extend(comp)
    return bytes(out), lengths


# ---------------------------------------------------------------------------
# _dither_fast
# ---------------------------------------------------------------------------


class Dither1bppEquivTest(unittest.TestCase):
    """`dither_row_1bpp` must reproduce the `255 - row > thr` pack."""

    def test_random_rows(self) -> None:
        rng = _rng()
        for width in (1, 7, 8, 9, 16, 31, 32, 33, 64, 100):
            for _ in range(8):
                row = _u8(width, rng)
                thr = _u8(width, rng)
                self.assertEqual(
                    _dither_fast.dither_row_1bpp(row, thr, width),
                    _ref_dither_1bpp(row, thr, width),
                    f"width={width}",
                )

    def test_extreme_rows_and_thresholds(self) -> None:
        for width in (1, 8, 17):
            for value in (0, 128, 255):
                row = np.full(width, value, dtype=np.uint8)
                for tval in (0, 128, 255):
                    thr = np.full(width, tval, dtype=np.uint8)
                    self.assertEqual(
                        _dither_fast.dither_row_1bpp(row, thr, width),
                        _ref_dither_1bpp(row, thr, width),
                        f"value={value} thr={tval} width={width}",
                    )

    def test_pixels_past_width_are_ignored(self) -> None:
        rng = _rng()
        width = 12
        row = _u8(width + 7, rng)
        thr = _u8(width + 7, rng)
        self.assertEqual(
            _dither_fast.dither_row_1bpp(row, thr, width),
            _ref_dither_1bpp(row, thr, width),
        )


class Dither4bppPatternEquivTest(unittest.TestCase):
    """`dither_row_4bpp_pattern` must reproduce the numpy BRCD gather.

    The BRCD pattern table is built synthetically (random bytes), the way
    `test_dither_tables.Native4bppPatternTest` does; no blob file is read.
    """

    @staticmethod
    def _patterns(n_ink: int, height: int, wb: int, rng: random.Random) -> tuple[np.ndarray, int]:
        prb = height * wb
        return _u8(n_ink * prb, rng).reshape(n_ink, prb), prb

    def test_random_rows(self) -> None:
        rng = _rng()
        height, wb = 32, 4
        for n_ink in (256, 200):
            patterns, prb = self._patterns(n_ink, height, wb, rng)
            flat = patterns.reshape(-1)
            for width in (2, 4, 8, 16, 32, 64):
                for _ in range(6):
                    row = _u8(width, rng)
                    for y in (0, 1, 31, 32, 157, 65535):
                        off = (y % height) * wb
                        self.assertEqual(
                            _dither_fast.dither_row_4bpp_pattern(row, flat, n_ink, prb, off, wb, width),
                            _ref_dither_4bpp(row, patterns, n_ink, prb, off, wb, width),
                            f"n_ink={n_ink} width={width} y={y}",
                        )

    def test_extreme_rows(self) -> None:
        rng = _rng()
        patterns, prb = self._patterns(256, 32, 4, rng)
        flat = patterns.reshape(-1)
        for value in (0, 128, 255):
            row = np.full(32, value, dtype=np.uint8)
            for y in range(0, 40):
                off = (y % 32) * 4
                self.assertEqual(
                    _dither_fast.dither_row_4bpp_pattern(row, flat, 256, prb, off, 4, 32),
                    _ref_dither_4bpp(row, patterns, 256, prb, off, 4, 32),
                    f"value={value} y={y}",
                )

    def test_odd_width_is_rejected(self) -> None:
        """The kernel documents an even-width contract; make it explicit."""
        rng = _rng()
        patterns, prb = self._patterns(256, 32, 4, rng)
        row = _u8(9, rng)
        with self.assertRaises(ValueError):
            _dither_fast.dither_row_4bpp_pattern(row, patterns.reshape(-1), 256, prb, 0, 4, 9)


class DitherReferenceFidelityTest(unittest.TestCase):
    """The inline 1bpp reference must match the real `dither` fallback.

    `dither.dither_channel_1bpp_arr` normally calls the kernel; forcing
    ``HAS_CYTHON_DITHER`` off exercises its pure-Python branch, which is what
    ``_ref_dither_1bpp`` reproduces.  This keeps the two from drifting apart.
    """

    def test_inline_reference_matches_the_module_fallback(self) -> None:
        rng = _rng()
        for width in (1, 7, 8, 9, 33, 100):
            row = _u8(width, rng)
            thr = _u8(width, rng)
            channel = dither.DitherChannel(width=width, height=1, threshold_matrix=thr.reshape(1, width))
            with mock.patch.object(dither, "HAS_CYTHON_DITHER", False):
                got = dither.dither_channel_1bpp_arr(row, 0, width, channel)
            self.assertEqual(got, _ref_dither_1bpp(row, thr, width), f"width={width}")


# ---------------------------------------------------------------------------
# _color_fast
# ---------------------------------------------------------------------------


class GatherKcmyEquivTest(unittest.TestCase):
    """`gather_kcmy` must reproduce the numpy inverse-LUT gather."""

    def test_random_rows(self) -> None:
        rng = _rng()
        lut = _random_inverse_lut()
        for width in (1, 2, 3, 7, 16, 64, 256):
            for _ in range(4):
                rgb = _u8(width * 3, rng)
                k, c, m, y = (np.empty(width, dtype=np.uint8) for _ in range(4))
                _color_fast.gather_kcmy(rgb, width, lut, k, c, m, y)
                ref = _ref_gather_planes(rgb, width, lut)
                self.assertTrue(
                    np.array_equal(np.stack([k, c, m, y]), ref),
                    f"width={width}",
                )

    def test_corner_colours(self) -> None:
        lut = _random_inverse_lut()
        rgb = np.array([0, 0, 0, 255, 255, 255, 255, 0, 0, 0, 255, 0, 0, 0, 255, 128, 128, 128], dtype=np.uint8)
        width = rgb.size // 3
        k, c, m, y = (np.empty(width, dtype=np.uint8) for _ in range(4))
        _color_fast.gather_kcmy(rgb, width, lut, k, c, m, y)
        self.assertTrue(np.array_equal(np.stack([k, c, m, y]), _ref_gather_planes(rgb, width, lut)))


class InterpKcmyEquivTest(unittest.TestCase):
    """`interp_kcmy` must reproduce `color_lut._rgb_to_cmyk_interp_arr`."""

    @staticmethod
    def _arrays(rng: random.Random) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        # Ink amounts are non-negative, like the real grid; the interpolation
        # rounding is then identical to the kernel's truncating integer divide.
        grid = _u8(_GRID_ENTRIES * 4, rng).astype(np.int32).reshape(_GRID_ENTRIES, 4)
        return grid, _random_weights(rng), color_lut._K_PRESET.copy()

    def _run(self, rgb: np.ndarray, grid: np.ndarray, weights: np.ndarray, black: np.ndarray) -> None:
        width = rgb.size // 3
        k, c, m, y = (np.empty(width, dtype=np.uint8) for _ in range(4))
        _color_fast.interp_kcmy(rgb, width, grid.reshape(-1), weights.reshape(-1), black, k, c, m, y)
        ref = _ref_interp_planes(rgb, width, grid, weights)
        self.assertTrue(np.array_equal(np.stack([k, c, m, y]), np.stack(ref)))

    def test_random_rows(self) -> None:
        rng = _rng()
        grid, weights, black = self._arrays(rng)
        for width in (1, 2, 8, 33, 64):
            for _ in range(5):
                self._run(_u8(width * 3, rng), grid, weights, black)

    def test_black_and_white_pixels(self) -> None:
        rng = _rng()
        grid, weights, black = self._arrays(rng)
        rgb = np.array(
            [0, 0, 0, 255, 255, 255, 255, 0, 0, 0, 255, 0, 0, 0, 255, 255, 0, 255, 0, 255, 255, 128, 128, 128],
            dtype=np.uint8,
        )
        self._run(rgb, grid, weights, black)

    def test_zero_total_weight_matches(self) -> None:
        """A zero interpolation total is clamped to 1 on both sides."""
        rng = _rng()
        grid, _, black = self._arrays(rng)
        weights = np.zeros((17, 289, 9), dtype=np.uint8)
        weights[:, :, 1:9] = _u8(_WEIGHT_ENTRIES, rng).reshape(17, 289, 9)[:, :, 1:9]
        self._run(_u8(24, rng), grid, weights, black)


# ---------------------------------------------------------------------------
# _rle_fast
# ---------------------------------------------------------------------------


class GroupBitsEquivTest(unittest.TestCase):
    """`group_bits` must reproduce `rle.group_bits_py`."""

    def test_random_and_edge_input(self) -> None:
        rng = _rng()
        cases = [b"", b"\x00", b"\xff", b"\x00" * 64, b"\xff" * 64, bytes(range(256))]
        cases += [rng.randbytes(n) for n in (1, 2, 3, 5, 7, 15, 40, 129)]
        for group_size in (10, 12, 20):
            for data in cases:
                self.assertEqual(
                    list(_rle_fast.group_bits(data, group_size)),
                    rle.group_bits_py(data, group_size),
                    f"group_size={group_size} len={len(data)}",
                )


class PackGroupsEquivTest(unittest.TestCase):
    """`pack_groups` must reproduce `rle.pack_groups_py`."""

    def test_random_and_edge_groups(self) -> None:
        rng = _rng()
        for group_size in (10, 12, 20):
            mask = (1 << group_size) - 1
            groups_cases = [
                [],
                [0],
                [mask],
                [0] * 37,
                [mask] * 37,
                [rng.randrange(mask + 1) for _ in range(200)],
                [rng.randrange(mask + 1) for _ in range(7)],
            ]
            for groups in groups_cases:
                self.assertEqual(
                    _rle_fast.pack_groups(groups, group_size),
                    rle.pack_groups_py(groups, group_size),
                    f"group_size={group_size} n={len(groups)}",
                )

    def test_round_trip_against_group_bits(self) -> None:
        """pack_groups(group_bits(x)) must agree with the pure-Python pair."""
        rng = _rng()
        for group_size in (10, 12, 20):
            data = rng.randbytes(53)
            self.assertEqual(
                _rle_fast.pack_groups(list(_rle_fast.group_bits(data, group_size)), group_size),
                rle.pack_groups_py(rle.group_bits_py(data, group_size), group_size),
            )


class EncodeSwRleEquivTest(unittest.TestCase):
    """`encode_sw_rle` must reproduce `sw_rle_encode` + `finalize_compressed`."""

    def _cases(self, rng: random.Random) -> list[bytes]:
        cases = [
            b"",
            b"\x00",
            b"\xff",
            b"\x00" * 4096,
            b"\xff" * 4096,
            bytes(range(256)) * 4,
            b"\x12\x34\x56" * 300,
        ]
        for _ in range(120):
            cases.append(rng.randbytes(rng.randrange(0, 400)))
        for _ in range(60):
            # Runs and strides are what the sliding-window states key on.
            period = rng.randrange(1, 5)
            pattern = rng.randbytes(period)
            cases.append((pattern * (rng.randrange(1, 300) // period + 1))[: rng.randrange(1, 300)])
        return cases

    def test_random_and_edge_input(self) -> None:
        rng = _rng()
        for bits in (10, 12, 20):
            for data in self._cases(rng):
                self.assertEqual(
                    _rle_fast.encode_sw_rle(data, bits),
                    _ref_encode_sw_rle(data, bits),
                    f"bits={bits} len={len(data)}",
                )

    def test_long_input_triggers_the_raw_fallback(self) -> None:
        """A long, high-entropy line must exercise `finalize_compressed`."""
        rng = _rng()
        for bits in (10, 12, 20):
            data = rng.randbytes(20000)
            self.assertEqual(_rle_fast.encode_sw_rle(data, bits), _ref_encode_sw_rle(data, bits))

    def test_plane_encoders_route_through_the_kernel(self) -> None:
        """The public encoders must use the same 12/20/10-bit settings."""
        rng = _rng()
        data = rng.randbytes(596)
        self.assertEqual(plane_encoders.encode_plane(data, "K"), _rle_fast.encode_sw_rle(data, 12))
        self.assertEqual(plane_encoders.encode_plane(data, "Y"), _rle_fast.encode_sw_rle(data, 12))
        self.assertEqual(plane_encoders.encode_c_plane(data), _rle_fast.encode_sw_rle(data, 20))
        self.assertEqual(plane_encoders.encode_m_plane_10(data), _rle_fast.encode_sw_rle(data, 10))


# ---------------------------------------------------------------------------
# _band_fast
# ---------------------------------------------------------------------------


class BandEquivTest(unittest.TestCase):
    """`render_band` must reproduce the per-line loop from `pipeline._render_page`."""

    @staticmethod
    def _thresholds(rng: random.Random, heights, sw: int) -> tuple[np.ndarray, ...]:
        return tuple(np.ascontiguousarray(_u8(h * sw, rng).reshape(h, sw)) for h in heights)

    def _call(self, rows, skip, width, first_line, sw, colour, thr):
        lengths = np.zeros((rows.shape[0], 4), dtype=np.int32)
        data = _band_fast.render_band(rows, skip, width, first_line, sw, *colour, *thr, lengths)
        return data, lengths

    def test_grid_interpolation_mode(self) -> None:
        rng = _rng()
        grid = _u8(_GRID_ENTRIES * 4, rng).astype(np.int32).reshape(_GRID_ENTRIES, 4)
        weights = _random_weights(rng)
        black = color_lut._K_PRESET.copy()
        colour = (np.zeros(0, dtype=np.uint8), grid.reshape(-1), weights.reshape(-1), black)
        heights = (80, 80, 24, 80)  # K/C/M are 80x80, Y is 24x24 in the real set

        for width, sw in ((16, 16), (13, 16), (31, 32), (7, 8), (1, 8), (64, 64)):
            for _ in range(3):
                n = 5
                rows = _u8(n * width * 3, rng).reshape(n, width * 3)
                skip = np.zeros(n, dtype=np.uint8)
                skip[rng.randrange(n)] = 1
                first_line = rng.randrange(0, 400)
                thr = self._thresholds(rng, heights, sw)

                got, got_len = self._call(rows, skip, width, first_line, sw, colour, thr)
                ref, ref_len = _ref_render_band(
                    rows, skip, width, first_line, sw, colour[0], grid, weights, black, thr
                )
                self.assertEqual(got, ref, f"width={width} sw={sw} first_line={first_line}")
                self.assertTrue(np.array_equal(got_len, ref_len), f"width={width} sw={sw}")

    def test_inverse_lut_mode(self) -> None:
        rng = _rng()
        lut = _random_inverse_lut()
        colour = (lut, np.empty(0, dtype=np.int32), np.empty(0, dtype=np.uint8), np.empty(0, dtype=np.int32))
        heights = (80, 80, 24, 80)

        width, sw, n = 32, 32, 4
        rows = _u8(n * width * 3, rng).reshape(n, width * 3)
        skip = np.zeros(n, dtype=np.uint8)
        first_line = 137
        thr = self._thresholds(rng, heights, sw)

        got, got_len = self._call(rows, skip, width, first_line, sw, colour, thr)
        ref, ref_len = _ref_render_band(
            rows, skip, width, first_line, sw, lut, None, None, color_lut._K_PRESET, thr
        )
        self.assertEqual(got, ref)
        self.assertTrue(np.array_equal(got_len, ref_len))

    def test_all_rows_skipped_is_empty(self) -> None:
        rng = _rng()
        grid = _u8(_GRID_ENTRIES * 4, rng).astype(np.int32).reshape(_GRID_ENTRIES, 4)
        weights = _random_weights(rng)
        colour = (np.zeros(0, dtype=np.uint8), grid.reshape(-1), weights.reshape(-1), color_lut._K_PRESET.copy())
        width, sw, n = 16, 16, 3
        rows = _u8(n * width * 3, rng).reshape(n, width * 3)
        skip = np.ones(n, dtype=np.uint8)
        thr = self._thresholds(rng, (80, 80, 24, 80), sw)

        got, got_len = self._call(rows, skip, width, 0, sw, colour, thr)
        self.assertEqual(got, b"")
        self.assertTrue(np.array_equal(got_len, np.zeros((n, 4), dtype=np.int32)))


if __name__ == "__main__":
    unittest.main(verbosity=2)
