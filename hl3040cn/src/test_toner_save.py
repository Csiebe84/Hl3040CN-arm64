#!/usr/bin/env python3
"""Regression tests for Toner Save Mode (BRTonerSaveMode).

Toner save does not touch the colour grid. It swaps the BRCD dither tables
for the `-TS` set, so the ink coverage drops without changing the separation:
on a solid black page the oracle emits a full-ink plane without the option and
a dithered plane with it. The port selects the tables by filename suffix
(`dither.load_brcd_tables`), so the tests check the suffix wiring and the fact
that the two table sets really differ.

These run without the Brother binary: they only need the installed `-TS`
tables, which is also what makes them useful in CI.
"""

from __future__ import annotations

import hashlib
import io
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import dither  # noqa: E402
import pipeline  # noqa: E402
from ppm import read_ppm  # noqa: E402
from settings import PrintSettings, Resolution  # noqa: E402
from test_blobs import require_blobs  # noqa: E402

LUT_DIR = Path(__file__).resolve().parent / "lut"
WIDTH, HEIGHT = 5100, 200


def render(rgb: tuple[int, int, int], *, toner_save: bool) -> bytes:
    """Filter one solid page and return the XL2HB session bytes.

    Pins Normal resolution explicitly. The `-TS` tables describe the Normal
    dither, and the assertion below is the Normal-mode behaviour the oracle
    shows; Fine is a separate, still-open defect (see FINE_HANDOVER.md). Relying
    on the class default would silently retarget these tests whenever that
    default changes.
    """
    header = b"P6\n%d %d\n255\n" % (WIDTH, HEIGHT)
    parsed = read_ppm(io.BytesIO(header + bytes(rgb) * WIDTH * HEIGHT))
    assert parsed is not None
    width, height, _maxval, pixels = parsed
    settings = PrintSettings()
    settings.page_size = "Letter"
    settings.resolution = Resolution.NORMAL
    settings.toner_save = toner_save
    out = io.BytesIO()
    pipeline.filter_page(width, height, pixels, settings, out)
    stream = out.getvalue()
    marker = b") BROTHER XL2HB;1;0\n"
    at = stream.find(marker)
    return stream[at:] if at >= 0 else stream


class TableSelectionTest(unittest.TestCase):
    """`load_brcd_tables` must pick the `-TS` files when asked to."""

    def test_toner_save_uses_the_ts_suffix(self):
        """The suffix map is what routes to the toner-save tables."""
        self.assertEqual(dither._BRCD_SUFFIX[False], "")
        self.assertEqual(dither._BRCD_SUFFIX[True], "-TS")

    @require_blobs(lut=True)
    def test_both_table_sets_load(self):
        """Both sets must exist and carry all four channels."""
        for toner_save in (False, True):
            with self.subTest(toner_save=toner_save):
                tables = dither.load_brcd_tables(str(LUT_DIR), toner_save=toner_save)
                self.assertIsNotNone(tables, "the BRCD set did not load")
                self.assertEqual(set(tables), set("KCMY"))

    @require_blobs(lut=True)
    def test_the_two_sets_differ(self):
        """If -TS equalled the plain set the option would be a no-op."""
        plain = dither.load_brcd_tables(str(LUT_DIR), toner_save=False)
        saved = dither.load_brcd_tables(str(LUT_DIR), toner_save=True)
        assert plain is not None and saved is not None
        for channel in "KCMY":
            with self.subTest(channel=channel):
                self.assertNotEqual(
                    hashlib.sha256(plain[channel].threshold_matrix.tobytes()).digest(),
                    hashlib.sha256(saved[channel].threshold_matrix.tobytes()).digest(),
                )

    @require_blobs(lut=True)
    def test_the_ts_files_are_actually_loaded(self):
        """Reading the files directly must give the same matrices."""
        tables = dither.load_brcd_tables(str(LUT_DIR), toner_save=True)
        assert tables is not None
        direct = dither.dither_load_brcd(str(LUT_DIR / "0600-k-TS_cache08.bin"))
        self.assertEqual(tables["K"].threshold_matrix.tobytes(), direct.threshold_matrix.tobytes())


@require_blobs(lut=True)
class TonerSaveOutputTest(unittest.TestCase):
    """The option must change the raster, not just the PJL header."""

    def test_black_page_changes(self):
        """A solid black page must dither differently with toner save."""
        self.assertNotEqual(
            render((0, 0, 0), toner_save=False),
            render((0, 0, 0), toner_save=True),
        )

    def test_grey_page_changes(self):
        """A mid grey must also dither differently."""
        self.assertNotEqual(
            render((128, 128, 128), toner_save=False),
            render((128, 128, 128), toner_save=True),
        )

    def test_a_saturated_colour_changes(self):
        """Toner save applies to the colour planes too."""
        self.assertNotEqual(
            render((0, 255, 255), toner_save=False),
            render((0, 255, 255), toner_save=True),
        )

    def test_rendering_is_deterministic(self):
        """Two identical renders must agree, or nothing above is meaningful."""
        for rgb in ((0, 0, 0), (128, 128, 128)):
            for toner_save in (False, True):
                with self.subTest(rgb=rgb, toner_save=toner_save):
                    self.assertEqual(
                        render(rgb, toner_save=toner_save),
                        render(rgb, toner_save=toner_save),
                    )


if __name__ == "__main__":
    unittest.main()
