#!/usr/bin/env python3
"""Regression tests for the Fine-mode (BRResolution=Fine) colour grid.

Fine selects a *distinct* separation grid, not the 600 dpi one the port used
before. The filter ships a `CAPT` (2400 dpi class) grid per profile/ImpGray, and
the difference is visible on mid greys: the 600 dpi `rgb_default` grid keeps a
black component (K=15 at RGB 128) while `rgb_capt` drops it to K=0. That is what
makes the oracle's Fine output omit the K plane at gray 128.

`transforms.color_table` picks the grid:

    resolution NORMAL -> rgb_default    capt=False
    resolution FINE   -> rgb_capt       capt=True
    VIVID + FINE      -> srgb_capt      capt=True
    NONE  + FINE      -> cmyk_default   capt=False

The name selection needs no blobs; the ink values do, so they are guarded with
`test_blobs.require_blobs` and skip on a checkout without Brother's colour grids.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import color_lut  # noqa: E402
import transforms  # noqa: E402
from settings import ColorMatching, PrintSettings, Resolution  # noqa: E402
from test_blobs import require_blobs  # noqa: E402

# (resolution, colour matching) -> (grid name, capt flag).
CAPT_SELECTION = [
    (Resolution.NORMAL, ColorMatching.NORMAL, "rgb_default", False),
    (Resolution.NORMAL, ColorMatching.VIVID, "srgb_default", False),
    (Resolution.NORMAL, ColorMatching.NONE, "cmyk_default", False),
    (Resolution.FINE, ColorMatching.NORMAL, "rgb_capt", True),
    (Resolution.FINE, ColorMatching.VIVID, "srgb_capt", True),
    (Resolution.FINE, ColorMatching.NONE, "cmyk_default", False),
]


def _settings(resolution: Resolution, matching: ColorMatching) -> PrintSettings:
    settings = PrintSettings()
    settings.resolution = resolution
    settings.color_matching = matching
    return settings


class CaptTableSelectionTest(unittest.TestCase):
    """`transforms.color_table` picks the grid from resolution and matching."""

    def test_grid_name_per_resolution_and_matching(self):
        for resolution, matching, name, _capt in CAPT_SELECTION:
            with self.subTest(resolution=resolution, matching=matching):
                self.assertEqual(transforms.color_table(_settings(resolution, matching)).name, name)

    def test_capt_flag_per_resolution_and_matching(self):
        for resolution, matching, _name, capt in CAPT_SELECTION:
            with self.subTest(resolution=resolution, matching=matching):
                self.assertEqual(transforms.color_table(_settings(resolution, matching)).capt, capt)

    def test_fine_is_a_distinct_grid_from_normal(self):
        """Fine must not silently reuse the 600 dpi separation."""
        for matching in (ColorMatching.NORMAL, ColorMatching.VIVID):
            with self.subTest(matching=matching):
                fine = transforms.color_table(_settings(Resolution.FINE, matching))
                normal = transforms.color_table(_settings(Resolution.NORMAL, matching))
                self.assertNotEqual(fine.name, normal.name)

    def test_cmyk_profile_is_unaffected_by_resolution(self):
        """Colour matching None has no CAPT grid: both resolutions use cmyk."""
        fine = transforms.color_table(_settings(Resolution.FINE, ColorMatching.NONE))
        normal = transforms.color_table(_settings(Resolution.NORMAL, ColorMatching.NONE))
        self.assertEqual(fine.name, normal.name)
        self.assertFalse(fine.capt)


@require_blobs(color_data=True)
class CaptInkTest(unittest.TestCase):
    """The CAPT grid drops the black component on mid greys."""

    def _k_ink(self, gray: int) -> int:
        table = color_lut.ColorTable(profile="rgb", capt=True)
        k, _c, _m, _y = color_lut.rgb_to_cmyk_lut_arr(bytes([gray, gray, gray]), 1, table)
        return 255 - int(k[0])

    def test_k_ink_at_measured_greys(self):
        # (gray, K ink) measured from the CAPT grid; K collapses to 0 at 128.
        for gray, want_k in ((64, 74), (128, 0), (192, 0)):
            with self.subTest(gray=gray):
                self.assertEqual(self._k_ink(gray), want_k)

    def test_capt_drops_black_that_the_600dpi_grid_keeps(self):
        """This is the property the K-plane omission at gray 128 depends on."""
        normal = color_lut.ColorTable(profile="rgb")
        capt = color_lut.ColorTable(profile="rgb", capt=True)
        row = bytes([128, 128, 128])
        normal_k = 255 - int(color_lut.rgb_to_cmyk_lut_arr(row, 1, normal)[0][0])
        capt_k = 255 - int(color_lut.rgb_to_cmyk_lut_arr(row, 1, capt)[0][0])
        self.assertGreater(normal_k, 0, "the 600 dpi grid is expected to carry black at gray 128")
        self.assertEqual(capt_k, 0, "the CAPT grid is expected to drop black at gray 128")


if __name__ == "__main__":
    unittest.main(verbosity=2)
