#!/usr/bin/env python3
"""Regression tests for the BRGray=OFF achromatic replacement.

With `BRGray=OFF` the printer separates pixels where R=G=B through the cmyk
grid instead of the profile grid; with `BRGray=ON` it uses the profile grid
for every pixel.  The two settings must therefore produce different output for
a grey page, and the same output for a page with no achromatic pixel.

The tests run without the Cython modules and without the Brother binary: they
only need the colour grids, so they also guard the pure-Python path that CI
uses.
"""

from __future__ import annotations

import io
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import color_lut  # noqa: E402
import pipeline  # noqa: E402
from ppm import read_ppm  # noqa: E402
from settings import PrintSettings  # noqa: E402

WIDTH, HEIGHT = 5100, 200


def page(rgb: tuple[int, int, int]) -> bytes:
    """A PPM of one solid colour."""
    header = b"P6\n%d %d\n255\n" % (WIDTH, HEIGHT)
    return header + bytes(rgb) * WIDTH * HEIGHT


# The PJL header carries `IMPROVEGRAY=ON` when BRGray is on, so the two
# settings never share a header. The raster comparison starts at the session.
SESSION_MARKER = b") BROTHER XL2HB;1;0\n"


def session(stream: bytes) -> bytes:
    """Drop the PJL header, keep the XL2HB session."""
    at = stream.find(SESSION_MARKER)
    return stream[at:] if at >= 0 else stream


def render(rgb: tuple[int, int, int], *, improve_gray: bool) -> bytes:
    """Filter one solid page and return the XL2HB session bytes."""
    parsed = read_ppm(io.BytesIO(page(rgb)))
    assert parsed is not None
    width, height, _maxval, pixels = parsed
    settings = PrintSettings()
    settings.page_size = "Letter"
    settings.improve_gray = improve_gray
    out = io.BytesIO()
    pipeline.filter_page(width, height, pixels, settings, out)
    return session(out.getvalue())


class GrayReplaceTableTest(unittest.TestCase):
    """The grid selection that drives the per-pixel replacement."""

    def test_replace_flag_selects_the_cmyk_grid(self):
        """With `gray_replace` set, achromatic pixels go through cmyk."""
        table = color_lut.ColorTable("rgb", gray_replace=True)
        self.assertEqual(color_lut.gray_replace_table(table), color_lut.ColorTable("cmyk"))

    def test_without_the_flag_there_is_no_replacement(self):
        """BRGray=ON leaves `gray_replace` clear, so nothing is replaced."""
        table = color_lut.ColorTable("rgb", gray_replace=False)
        self.assertIsNone(color_lut.gray_replace_table(table))

    def test_cmyk_matching_is_its_own_replacement(self):
        """With colour matching None the cmyk grid is already in use."""
        table = color_lut.ColorTable("cmyk", gray_replace=True)
        self.assertIsNone(color_lut.gray_replace_table(table))

    def test_glossy_and_toner_save_keep_the_replacement(self):
        """The variant must not disable the replacement."""
        for variant in ("density2", "glossy"):
            table = color_lut.ColorTable("rgb", gray_replace=True, variant=variant)
            self.assertEqual(color_lut.gray_replace_table(table), color_lut.ColorTable("cmyk"))

    def test_gray_grid_differs_from_the_profile_grid(self):
        """A replacement that returned the same grid would be a no-op."""
        profile = color_lut.interp_arrays(color_lut.ColorTable("rgb", improve_gray=True))[0]
        gray = color_lut.interp_arrays(color_lut.ColorTable("cmyk"))[0]
        self.assertFalse((profile == gray).all(), "cmyk and rgb grids are identical")

    def test_color_table_sets_the_flag_from_the_setting(self):
        """`transforms.color_table` is what wires BRGray to `gray_replace`."""
        import transforms

        for improve_gray, expected in ((False, True), (True, False)):
            settings = PrintSettings()
            settings.improve_gray = improve_gray
            table = transforms.color_table(settings)
            self.assertEqual(table.gray_replace, expected)
            self.assertTrue(table.improve_gray, "rgb/srgb always use the *_ig grid")


class GrayOutputTest(unittest.TestCase):
    """End-to-end: the setting must change a grey page and not a coloured one."""

    def test_grey_page_differs_between_on_and_off(self):
        """A grey page must not render the same with BRGray on and off."""
        on = render((128, 128, 128), improve_gray=True)
        off = render((128, 128, 128), improve_gray=False)
        self.assertNotEqual(on, off)

    def test_black_page_is_unaffected(self):
        """Pure black is achromatic, but both grids give it full ink."""
        self.assertEqual(
            render((0, 0, 0), improve_gray=True),
            render((0, 0, 0), improve_gray=False),
        )

    def test_dark_grey_page_differs_between_on_and_off(self):
        """A grey that is not the extremes must show the grid difference."""
        on = render((64, 64, 64), improve_gray=True)
        off = render((64, 64, 64), improve_gray=False)
        self.assertNotEqual(on, off)

    def test_saturated_page_is_unaffected(self):
        """A page with no R=G=B pixel must render identically either way."""
        on = render((255, 0, 0), improve_gray=True)
        off = render((255, 0, 0), improve_gray=False)
        self.assertEqual(on, off)

    def test_white_page_is_unaffected(self):
        """White is R=G=B, but both grids map it to no ink."""
        self.assertEqual(
            render((255, 255, 255), improve_gray=True),
            render((255, 255, 255), improve_gray=False),
        )


class KernelParityTest(unittest.TestCase):
    """The Cython kernel must agree with the pure-Python path."""

    def _render_with(self, rgb: tuple[int, int, int], improve_gray: bool, *, kernel: bool) -> bytes:
        original = pipeline.HAS_BAND_KERNEL
        pipeline.HAS_BAND_KERNEL = kernel
        try:
            return render(rgb, improve_gray=improve_gray)
        finally:
            pipeline.HAS_BAND_KERNEL = original

    @unittest.skipUnless(pipeline.HAS_BAND_KERNEL, "Cython band kernel not built")
    def test_kernel_matches_the_python_path(self):
        """Both renderers must produce identical bytes, grey and colour."""
        for rgb in ((128, 128, 128), (0, 0, 0), (255, 0, 0), (255, 255, 255)):
            for improve_gray in (True, False):
                with self.subTest(rgb=rgb, improve_gray=improve_gray):
                    self.assertEqual(
                        self._render_with(rgb, improve_gray, kernel=True),
                        self._render_with(rgb, improve_gray, kernel=False),
                    )


if __name__ == "__main__":
    unittest.main()
