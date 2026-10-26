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


if __name__ == "__main__":
    unittest.main(verbosity=2)
