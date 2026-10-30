#!/usr/bin/env python3
"""Regression tests for Fine mode (BRResolution=Fine).

Fine selects the `capt` dither tables and a two-stage encoder, and it packs
four bits per pixel, so the BeginImage source width is rounded to an 8-pixel
boundary (8 px = one byte at 4 bpp), not Normal's 32.  That rounding used to
return the raw paper width, which made every Fine page 1-2 bytes narrow per
line; these tests pin it against the values measured from Brother's filter.

They run without the Brother binary (CI has none): every expectation is a
table geometry, a header value, or a structural invariant, never an oracle
byte comparison.
"""

from __future__ import annotations

import io
import sys
import unittest
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
# `band`/`pclxl` (the XL2HB stream parser) live in the repository's top-level
# `src/`, two levels up from `hl3040cn/src/`. They are optional: the header
# checks below do not need them, and CI may not carry that directory.
sys.path.insert(0, str(HERE.parents[1] / "src"))

import dither  # noqa: E402
import pipeline  # noqa: E402
import xl2hb  # noqa: E402
from ppm import read_ppm  # noqa: E402
from settings import ColorMatching, PrintSettings, Resolution  # noqa: E402
from test_blobs import require_blobs  # noqa: E402

LUT_DIR = Path(__file__).resolve().parent / "lut"
WIDTH, HEIGHT = 5100, 200

# (page, raw paper width, Fine source width measured from the filter).
FINE_WIDTHS = [
    ("Letter", 5100, 5104),
    ("A4", 4958, 4960),
    ("A5", 3500, 3504),
    ("Executive", 4350, 4352),
    ("EnvDL", 2600, 2600),
    ("Br3x5", 1800, 1800),
    ("EnvPRC5Rotated", 5200, 5200),
]


def render(rgb: tuple[int, int, int], *, resolution: Resolution = Resolution.FINE) -> bytes:
    """Filter one solid page and return the full XL2HB job bytes."""
    header = b"P6\n%d %d\n255\n" % (WIDTH, HEIGHT)
    parsed = read_ppm(io.BytesIO(header + bytes(rgb) * WIDTH * HEIGHT))
    assert parsed is not None
    width, height, _maxval, pixels = parsed
    settings = PrintSettings()
    settings.page_size = "Letter"
    settings.color_matching = ColorMatching.NORMAL
    settings.resolution = resolution
    out = io.BytesIO()
    pipeline.filter_page(width, height, pixels, settings, out)
    return out.getvalue()


class FineWidthTest(unittest.TestCase):
    """`get_image_dimensions_fine` must round the paper width up to 8."""

    def test_measured_widths(self):
        for page, raw, want in FINE_WIDTHS:
            with self.subTest(page=page):
                got, _ = xl2hb.get_image_dimensions_fine(page)
                self.assertEqual(got, want, f"{page}: raw {raw}, want {want}, got {got}")

    def test_width_is_eight_aligned(self):
        for page, *_ in FINE_WIDTHS:
            with self.subTest(page=page):
                got, _ = xl2hb.get_image_dimensions_fine(page)
                self.assertEqual(got % 8, 0, f"{page}: {got} is not a multiple of 8")

    def test_fine_is_narrower_than_normal(self):
        """Fine's boundary is 8, Normal's is 32; Fine must never be wider."""
        for page, *_ in FINE_WIDTHS:
            with self.subTest(page=page):
                fine, _ = xl2hb.get_image_dimensions_fine(page)
                normal, _ = xl2hb.get_image_dimensions(page)
                self.assertLessEqual(fine, normal)


@require_blobs(lut=True)
class FineDitherTableTest(unittest.TestCase):
    """Fine must select the `capt` table set, not the Normal `0600` set."""

    def test_prefix_selects_capt_for_fine(self):
        self.assertEqual(dither._BRCD_PREFIX[True], "capt")
        self.assertEqual(dither._BRCD_PREFIX[False], "0600")

    def test_capt_tables_load(self):
        tables = dither.load_dither_tables(str(LUT_DIR), fine=True, toner_save=False)
        self.assertEqual(set(tables), set("KCMY"))
        # Fine K/Y are 96x12 and C/M are 160x20 in the cache08 capt set.
        self.assertEqual((tables["K"].width, tables["K"].height), (96, 12))
        self.assertEqual((tables["C"].width, tables["C"].height), (160, 20))
        self.assertEqual((tables["Y"].width, tables["Y"].height), (96, 12))

    def test_fine_and_normal_tables_differ(self):
        fine = dither.load_dither_tables(str(LUT_DIR), fine=True, toner_save=False)
        normal = dither.load_dither_tables(str(LUT_DIR), fine=False, toner_save=False)
        for channel in "KCMY":
            with self.subTest(channel=channel):
                self.assertNotEqual(
                    (fine[channel].width, fine[channel].height),
                    (normal[channel].width, normal[channel].height),
                )


class FineStretchTest(unittest.TestCase):
    """The 96 px Fine screen rows (Y and K) are emitted verbatim.

    The filter does not widen a screen row; the earlier "4/3 stretch" of Y/K
    rows was a workaround for a stage-1 encoder bug (see
    `FineEncoderTest.test_lo_zero_run_white_token`).  With the encoder fixed
    every screen row -- 96 px (wb=12) and 160 px (wb=20) alike -- is packed
    straight through.  These checks are self-contained: they build synthetic
    patterns, so they do not need Brother's blobs.
    """

    @staticmethod
    def _channel(width: int, row_bytes: bytes) -> dither.DitherChannel:
        # One pattern row, replicated for every ink level.
        wb = width // 8
        pats = np.tile(np.frombuffer(row_bytes, dtype=np.uint8), (256, 1))
        return dither.DitherChannel(width=width, height=1, threshold_matrix=np.zeros((1, width), np.uint8),
                                    patterns=pats)

    def test_intermediate_levels_pass_through_verbatim(self):
        # 0xAA: both nibbles 10 (intermediate).  No zero bytes are inserted.
        chan = self._channel(24, bytes([0x0A, 0x0A, 0x0A]))
        row = np.zeros(24, dtype=np.uint8)
        out = dither.dither_channel_4bpp_pattern_arr(row, 0, 24, chan)
        self.assertEqual(out, bytes([0xAA]) * 12)

    def test_row_length_is_always_width_over_two(self):
        chan = self._channel(24, bytes([0x0F, 0x00, 0x0F]))
        row = np.zeros(24, dtype=np.uint8)
        out = dither.dither_channel_4bpp_pattern_arr(row, 0, 24, chan)
        self.assertEqual(len(out), 12)

    def test_non_multiple_of_three_width_is_verbatim(self):
        # wb = 5; 0xAA must pass through verbatim.
        chan = self._channel(40, bytes([0x0A, 0x0A, 0x0A, 0x0A, 0x0A]))
        row = np.zeros(40, dtype=np.uint8)
        out = dither.dither_channel_4bpp_pattern_arr(row, 0, 40, chan)
        self.assertEqual(out, bytes([0xAA]) * 20)

    @require_blobs(lut=True)
    def test_capt_rows_are_never_stretched(self):
        tables = dither.load_dither_tables(str(LUT_DIR), fine=True, toner_save=False)
        for name in ("C", "M", "Y", "K"):
            chan = tables[name]
            with self.subTest(channel=name):
                for y in range(chan.height):
                    for ink in (1, 4, 64, 111, 200):
                        out = dither.dither_channel_4bpp_pattern_arr(
                            np.full(5104, 255 - ink, np.uint8), y, 5104, chan
                        )
                        self.assertEqual(len(out), 5104 // 2)



class FineHeaderTest(unittest.TestCase):
    """The Fine BeginImage header must describe 4 bpp at the 8-aligned width."""

    @classmethod
    def setUpClass(cls):
        import pclxl

        cls.job = render((128, 128, 128))
        cls.ops = pclxl.parse(cls.job)

    def test_source_width_matches_get_image_dimensions_fine(self):
        begin = next(op for op in self.ops if op.name == "BeginImage")
        self.assertEqual(begin.attrs["SourceWidth"], 5104)

    def test_color_depth_is_one(self):
        # ColorDepth=1 selects Fine's 4 bpp planes; Normal sends 0.
        begin = next(op for op in self.ops if op.name == "BeginImage")
        self.assertEqual(begin.attrs["ColorDepth"], 1)

    def test_pjl_reports_600_and_aptmode_on4(self):
        self.assertIn(b"APTMODE=ON4", self.job)
        self.assertIn(b"RESOLUTION=600", self.job)

    def test_every_block_is_4bpp_at_fine_width(self):
        # 4 bpp: two pixels per byte. The plane header carries the row width.
        import band

        blocks = band.decode_blocks(self.ops)
        self.assertTrue(blocks, "Fine produced no raster blocks")
        for block in blocks:
            self.assertEqual(block.header.row_width, 5104 // 2)
            self.assertEqual(block.header.bit_depth, 12)

    def test_normal_uses_thirty_two_aligned_width(self):
        import pclxl

        normal = pclxl.parse(render((128, 128, 128), resolution=Resolution.NORMAL))
        begin = next(op for op in normal if op.name == "BeginImage")
        self.assertEqual(begin.attrs["SourceWidth"], 5120)
        self.assertEqual(begin.attrs["ColorDepth"], 0)


class FineDeterminismTest(unittest.TestCase):
    def test_rendering_is_deterministic(self):
        for rgb in ((0, 0, 0), (128, 128, 128), (0, 255, 255)):
            with self.subTest(rgb=rgb):
                self.assertEqual(render(rgb), render(rgb))

    def test_fine_differs_from_normal(self):
        """Fine must not silently fall back to the Normal path."""
        for rgb in ((0, 0, 0), (128, 128, 128)):
            with self.subTest(rgb=rgb):
                self.assertNotEqual(render(rgb), render(rgb, resolution=Resolution.NORMAL))


class FineEncoderTest(unittest.TestCase):
    """Structural checks on the two-stage Fine encoder."""

    def test_empty_scanline_is_empty(self):
        from fine_encoder import encode_fine_plane

        self.assertEqual(encode_fine_plane(bytes(2552)), b"")

    def test_encoding_is_deterministic(self):
        from fine_encoder import encode_fine_plane

        data = bytes(range(256)) * 10
        self.assertEqual(encode_fine_plane(data), encode_fine_plane(data))

    def test_lo_zero_run_white_token(self):
        # Regression for the mixed-colour row divergence.  In the `lo==0,
        # hi!=0, run_white!=0` branch the filter emits `run_white*8`, not
        # `run_white*8-8`.  The off-by-one produced 0xB2 where the oracle
        # emits 0xBA (and, before the encoder was fixed, was papered over by
        # a spurious 4/3 stretch of the Y/K screen rows).
        from fine_encoder import compress_rle_preencode

        # hi=0x60, lo=0, with a white run capped at 3 bytes -> 3*8 | 2 | 0xA0.
        self.assertEqual(compress_rle_preencode(bytes([0, 0, 0, 0, 0x60])), bytes.fromhex("10ba"))


class Stage2LosslessTest(unittest.TestCase):
    """Stage 2 must never change the image, only its size.

    Stage 2 is a pure compression layer on top of Stage 1, and Stage 1 is the
    raster.  Brother's filter tokenises the same Stage-1 bytes differently (it
    finds longer stride-3 patterns where this encoder emits literals), so the
    port's output is larger, but the decoded pixels are identical.  These tests
    pin that property so the size gap is never mistaken for a rendering bug.
    """

    @classmethod
    def setUpClass(cls):
        # `fine_decode` (the Stage-2 inverse) lives in the repository's tools/.
        tools = HERE.parents[1] / "tools"
        if str(tools) not in sys.path:
            sys.path.insert(0, str(tools))
        try:
            import fine_decode  # noqa: F401
        except ImportError:  # pragma: no cover - tools/ absent in some checkouts
            raise unittest.SkipTest("tools/fine_decode.py is not available")

    def _roundtrip(self, stage1: bytes) -> bool:
        from fine_decode import decode_stage2
        from fine_encoder import compress_pattern_encode

        return decode_stage2(compress_pattern_encode(stage1)) == stage1

    def test_roundtrip_on_repeating_runs(self):
        # Every stride the encoder knows, plus a literal-heavy tail.
        for data in (
            bytes([0x55]) * 40,               # stride 1
            bytes([0x11, 0x22]) * 20,         # stride 2
            bytes([0x11, 0x22, 0x33]) * 15,   # stride 3
            bytes(range(0x10, 0x30)),         # literals only
            bytes([0x10]) * 3 + bytes([0xAA, 0xBB]) * 7 + bytes([0x11]) * 9,
        ):
            with self.subTest(data=data[:6].hex()):
                self.assertTrue(self._roundtrip(data))

    def test_roundtrip_on_stage1_output(self):
        # Stage 1 output is what Stage 2 actually sees in production.
        from fine_encoder import compress_rle_preencode

        for raw in (
            bytes(300),                       # white run
            bytes([0xFF]) * 300,              # black run
            bytes([0x12, 0x34]) * 150,        # mixed nibbles
            bytes(64) + bytes([0xFF]) * 64,
        ):
            with self.subTest(raw=raw[:4].hex()):
                self.assertTrue(self._roundtrip(compress_rle_preencode(raw)))

    def test_empty_input_stays_empty(self):
        from fine_encoder import compress_pattern_encode

        self.assertEqual(compress_pattern_encode(b""), b"")


if __name__ == "__main__":
    unittest.main(verbosity=2)
