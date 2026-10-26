#!/usr/bin/env python3
"""Regression tests for BRGray (ImpGray) colour-grid selection.

BRGray is a whole-page grid selector, exactly like the colour matching: the
filter embeds an ImpGray=ON and an ImpGray=OFF grid per profile and applies the
selected one to *every* pixel.  It is not a per-pixel test, so a saturated
colour changes with BRGray too, and a grey page changes as well.  With BRGray=ON
the ImpGray=ON grid is used, with BRGray=OFF the ImpGray=OFF grid.

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
from settings import ColorMatching, PrintSettings  # noqa: E402
from test_blobs import require_blobs  # noqa: E402

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


def render(
    rgb: tuple[int, int, int], *, improve_gray: bool, matching: ColorMatching = ColorMatching.NORMAL
) -> bytes:
    """Filter one solid page and return the XL2HB session bytes."""
    parsed = read_ppm(io.BytesIO(page(rgb)))
    assert parsed is not None
    width, height, _maxval, pixels = parsed
    settings = PrintSettings()
    settings.page_size = "Letter"
    settings.color_matching = matching
    settings.improve_gray = improve_gray
    out = io.BytesIO()
    pipeline.filter_page(width, height, pixels, settings, out)
    return session(out.getvalue())


class ColorTableSelectionTest(unittest.TestCase):
    """`transforms.color_table` picks the grid from the settings."""

    def test_color_table_selects_the_grid_from_the_settings(self):
        """BRGray and the colour matching both choose the grid, per page."""
        import transforms

        for matching, profile in (
            (ColorMatching.NORMAL, "rgb"),
            (ColorMatching.VIVID, "srgb"),
            (ColorMatching.NONE, "cmyk"),
        ):
            for improve_gray in (False, True):
                with self.subTest(matching=matching, improve_gray=improve_gray):
                    settings = PrintSettings()
                    settings.color_matching = matching
                    settings.improve_gray = improve_gray
                    table = transforms.color_table(settings)
                    self.assertEqual(table.profile, profile)
                    self.assertEqual(table.improve_gray, improve_gray)

    def test_gray_on_and_off_use_different_grids(self):
        """The ImpGray=ON and ImpGray=OFF grids must be distinct tables."""
        on = color_lut.ColorTable("rgb", improve_gray=True)
        off = color_lut.ColorTable("rgb", improve_gray=False)
        self.assertNotEqual(on.name, off.name)

    @require_blobs(color_data=True)
    def test_gray_grids_differ_from_each_other(self):
        """A selector that returned the same grid would be a no-op."""
        on = color_lut.interp_arrays(color_lut.ColorTable("rgb", improve_gray=True))[0]
        off = color_lut.interp_arrays(color_lut.ColorTable("rgb", improve_gray=False))[0]
        self.assertFalse((on == off).all(), "ImpGray=ON and ImpGray=OFF grids are identical")


@require_blobs(color_data=True)
class GrayOutputTest(unittest.TestCase):
    """End-to-end: BRGray changes every page, grey or saturated alike."""

    def test_grey_page_differs_between_on_and_off(self):
        """A grey page must not render the same with BRGray on and off."""
        self.assertNotEqual(
            render((128, 128, 128), improve_gray=True),
            render((128, 128, 128), improve_gray=False),
        )

    def test_dark_grey_page_differs_between_on_and_off(self):
        """A grey that is not the extremes must show the grid difference."""
        self.assertNotEqual(
            render((64, 64, 64), improve_gray=True),
            render((64, 64, 64), improve_gray=False),
        )

    def test_saturated_page_differs_between_on_and_off(self):
        """BRGray is per page, not per pixel: a saturated colour changes too."""
        for rgb in ((100, 200, 50), (200, 50, 50), (60, 120, 220)):
            with self.subTest(rgb=rgb):
                self.assertNotEqual(
                    render(rgb, improve_gray=True),
                    render(rgb, improve_gray=False),
                )

    def test_black_page_is_unaffected(self):
        """Both ImpGray grids map pure black to full ink."""
        self.assertEqual(
            render((0, 0, 0), improve_gray=True),
            render((0, 0, 0), improve_gray=False),
        )

    def test_white_page_is_unaffected(self):
        """Both ImpGray grids map white to no ink."""
        self.assertEqual(
            render((255, 255, 255), improve_gray=True),
            render((255, 255, 255), improve_gray=False),
        )


class KernelParityTest(unittest.TestCase):
    """The Cython kernel must agree with the pure-Python path."""

    def _render_with(self, rgb: tuple[int, int, int], improve_gray: bool, kernel: bool) -> bytes:
        original = pipeline.HAS_BAND_KERNEL
        pipeline.HAS_BAND_KERNEL = kernel
        try:
            return render(rgb, improve_gray=improve_gray)
        finally:
            pipeline.HAS_BAND_KERNEL = original

    @unittest.skipUnless(pipeline.HAS_BAND_KERNEL, "Cython band kernel not built")
    @require_blobs(color_data=True)
    def test_kernel_matches_the_python_path(self):
        """Both renderers must produce identical bytes, grey and colour."""
        for rgb in ((128, 128, 128), (0, 0, 0), (100, 200, 50), (255, 255, 255)):
            for improve_gray in (True, False):
                with self.subTest(rgb=rgb, improve_gray=improve_gray):
                    self.assertEqual(
                        self._render_with(rgb, improve_gray, True),
                        self._render_with(rgb, improve_gray, False),
                    )


if __name__ == "__main__":
    unittest.main()
