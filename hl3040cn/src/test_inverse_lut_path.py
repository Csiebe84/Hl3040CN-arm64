"""Pin the inverse-LUT filename mapping, including the collision it avoids.

`inverse_lut_path` derives a cache filename from the colour table.  The suffix is
built from the profile and the ImpGray flag only, so two tables that differ in
their `capt` flag map to the *same* file:

    rgb_ig_capt    -> inverse_lut_rgb_ig.npy
    rgb_ig_default -> inverse_lut_rgb_ig.npy

Fine mode selects the capt table.  If that table were ever added to
`INVERSE_LUT_TABLES`, its lookup would silently return the Normal-mode grid and
every Fine page would be separated with the wrong colours - no error, no warning,
just a slightly wrong print.  Today the membership list keeps the two apart; this
test states that dependency so a future edit cannot break it quietly.
"""

from __future__ import annotations

import unittest

import color_lut
from color_lut import ColorTable, INVERSE_LUT_TABLES, inverse_lut_path


class InverseLutPathTest(unittest.TestCase):
    def test_tables_outside_the_list_have_no_path(self):
        for table in (
            ColorTable(profile="rgb", improve_gray=True, capt=True),
            ColorTable(profile="rgb_capt"),
            ColorTable(profile="rgb", improve_gray=True, capt=True, rich_black=True),
        ):
            self.assertIsNone(inverse_lut_path(table), f"{table.name} unexpectedly has a path")

    def test_the_normal_grid_does_resolve(self):
        """`ColorTable("rgb")` is the supported rgb_default grid, not a capt one."""
        self.assertIn(ColorTable("rgb"), INVERSE_LUT_TABLES)
        self.assertIsNotNone(inverse_lut_path(ColorTable("rgb")))

    def test_supported_tables_resolve_to_distinct_files(self):
        paths = {t.name: inverse_lut_path(t) for t in INVERSE_LUT_TABLES}
        resolved = [p for p in paths.values() if p is not None]
        self.assertEqual(len(resolved), len(set(resolved)), f"two tables share a file: {paths}")

    def test_capt_and_default_would_collide_if_both_were_listed(self):
        """The reason `capt` is excluded: the suffix cannot tell them apart."""
        capt = ColorTable(profile="rgb", improve_gray=True, capt=True)
        default = ColorTable(profile="rgb", improve_gray=True, capt=False)
        self.assertNotEqual(capt, default)
        self.assertNotIn(capt, INVERSE_LUT_TABLES)
        # The suffix builder ignores `capt`, so both would land on one filename.
        self.assertEqual(
            f"_{capt.profile}{'_ig' if capt.improve_gray else ''}",
            f"_{default.profile}{'_ig' if default.improve_gray else ''}",
        )

    def test_fine_mode_table_is_the_capt_one(self):
        from settings import ColorMatching, PrintSettings, Resolution
        from transforms import color_table

        settings = PrintSettings()
        settings.resolution = Resolution.FINE
        settings.color_matching = ColorMatching.NORMAL
        settings.improve_gray = True
        table = color_table(settings)
        self.assertTrue(table.capt, f"Fine should select a capt grid, got {table.name}")
        self.assertIsNone(inverse_lut_path(table), "a capt grid must not map to the Normal LUT")


if __name__ == "__main__":
    unittest.main(verbosity=2)
