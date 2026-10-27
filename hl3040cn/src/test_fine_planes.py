#!/usr/bin/env python3
"""Regression tests for Fine-mode plane presence.

The filter emits a `ReadImage` block only for a plane that carried ink. The port
does the same *without a special case*: `pipeline.filter_page` accumulates
compressed scanlines per plane and `write_plane` skips a plane whose buffer is
empty. An empty compressed scanline is exactly "this plane has no ink here".

For a solid grey page at Fine resolution that makes the plane set a function of
the CAPT separation alone (see `test_fine_capt_table`):

    gray   0 -> {K}          black ink only
    gray  64 -> {C, K, M, Y} K ink is 74, so K is emitted
    gray 128 -> {C, M, Y}    K ink is 0, so no K plane
    gray 192 -> {C, M, Y}    K ink is 0

These render a short (few-hundred-row) solid page and read the plane ids back
from the raster blocks, so they need the Brother dither tables and the XL2HB
parser; both are guarded so a CI checkout without the blobs still passes.
"""

from __future__ import annotations

import io
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
# `band`/`pclxl` (the XL2HB stream parser) live in the repository's top-level
# `src/`, two levels up from `hl3040cn/src/`.
sys.path.insert(0, str(HERE.parents[1] / "src"))

import pipeline  # noqa: E402
from ppm import read_ppm  # noqa: E402
from settings import ColorMatching, PrintSettings, Resolution  # noqa: E402
from test_blobs import require_blobs  # noqa: E402

WIDTH, HEIGHT = 5100, 256

# (gray, expected plane set). The rule is per-plane presence, not size.
PLANE_SETS = [
    (0, {"K"}),
    (64, {"C", "K", "M", "Y"}),
    (128, {"C", "M", "Y"}),
    (192, {"C", "M", "Y"}),
]


def render(rgb: tuple[int, int, int]) -> bytes:
    """Filter one solid Fine page and return the full XL2HB job bytes."""
    header = b"P6\n%d %d\n255\n" % (WIDTH, HEIGHT)
    parsed = read_ppm(io.BytesIO(header + bytes(rgb) * WIDTH * HEIGHT))
    assert parsed is not None
    width, height, _maxval, pixels = parsed
    settings = PrintSettings()
    settings.page_size = "Letter"
    settings.color_matching = ColorMatching.NORMAL
    settings.resolution = Resolution.FINE
    out = io.BytesIO()
    pipeline.filter_page(width, height, pixels, settings, out)
    return out.getvalue()


def plane_names(job: bytes) -> set[str]:
    """The set of plane names that carry a raster block in `job`."""
    import band
    import pclxl

    return {block.plane_name for block in band.decode_blocks(pclxl.parse(job))}


@require_blobs(lut=True)
class PlanePresenceTest(unittest.TestCase):
    """The plane set falls out of which planes accumulated a non-empty line."""

    def test_plane_set_per_grey(self):
        for gray, want in PLANE_SETS:
            with self.subTest(gray=gray):
                self.assertEqual(plane_names(render((gray, gray, gray))), want)

    def test_k_is_emitted_at_dark_grey_but_not_mid_grey(self):
        """The K plane tracks the CAPT K ink (74 at gray 64, 0 at gray 128)."""
        self.assertIn("K", plane_names(render((64, 64, 64))))
        self.assertNotIn("K", plane_names(render((128, 128, 128))))

    def test_black_page_emits_only_k(self):
        self.assertEqual(plane_names(render((0, 0, 0))), {"K"})


if __name__ == "__main__":
    unittest.main(verbosity=2)
