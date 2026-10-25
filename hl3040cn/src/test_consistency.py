#!/usr/bin/env python3
"""Consistency tests across the PPD, the enums, and the lookup tables.

These pin the seams that a port from another model tends to break silently:
the PPD is the source of truth for what a job can ask for, and every name in
it must resolve through `PageSize` and exist in the tables the encoder reads.

Three real bugs motivated this file, all of them fatal at print time but
invisible at install time:

* `PAPER_SIZES` was keyed "B5"/"B6" while the enum values are "ISOB5"/"ISOB6",
  so every B5/B6 job raised KeyError in `get_image_dimensions`.
* `BrA4Long` was missing from `PAPER_SIZES`, `MEDIA_SIZE` and `PageRegion`,
  although Brother's own 3040 PPD offers the size.
* The PPD advertised duplex printing, which the HL-3040CN does not have.
"""
import importlib.machinery
import importlib.util
import re
import unittest
from pathlib import Path

import settings
import xl2hb
from settings import InputSlot, MediaType, PageSize

ROOT = Path(__file__).resolve().parent.parent
PPD = ROOT / "cups" / "brhl3040cn.ppd"
FILTER = ROOT / "cups" / "brhl3040cn-filter"


def load_filter():
    """Load the CUPS filter script, which has no .py suffix.

    Returns:
        The filter module.
    """
    loader = importlib.machinery.SourceFileLoader("brhl3040cn_filter", str(FILTER))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def ppd_lines(keyword):
    """All values of one PPD keyword, without the group suffix.

    Returns:
        Set of group names, e.g. {"A4", "Letter"} for "*PageSize A4/A4: ...".
    """
    names = set()
    for line in PPD.read_text(encoding="latin-1").splitlines():
        if line.startswith(f"*{keyword} "):
            names.add(line.split()[1].split("/")[0])
    return names


def ppd_paper_dimensions():
    """PaperDimension of every size in the PPD, in points.

    Returns:
        Mapping of group name to (width, height) rounded to whole points.
    """
    dims = {}
    for line in PPD.read_text(encoding="latin-1").splitlines():
        if line.startswith("*PaperDimension "):
            name = line.split()[1].split("/")[0]
            width, height = line.split('"')[1].split()
            dims[name] = (round(float(width)), round(float(height)))
    return dims


def _resolves(name):
    """Whether a PPD size name maps onto a PageSize member.

    Returns:
        True if PageSize accepts the name (directly or through _missing_).
    """
    try:
        PageSize(name)
    except ValueError:
        return False
    return True


class PageSizeCoverageTest(unittest.TestCase):
    """Every PageSize the PPD offers must resolve to real dimensions."""

    def test_enum_covers_the_ppd_page_sizes(self):
        # The PPD may spell a size differently (PostCard vs Postcard); the
        # alias in _missing_ is what bridges it, so resolve before comparing.
        missing = [s for s in ppd_lines("PageSize") if not _resolves(s)]
        self.assertEqual(missing, [], f"PPD sizes that do not resolve: {sorted(missing)}")

    def test_enum_values_have_paper_sizes(self):
        missing = {s.value for s in PageSize} - set(xl2hb.PAPER_SIZES)
        self.assertEqual(missing, set(), f"enum values without PAPER_SIZES: {sorted(missing)}")

    def test_enum_values_have_media_size(self):
        missing = {s.value for s in PageSize} - set(xl2hb.MEDIA_SIZE)
        self.assertEqual(missing, set(), f"enum values without MEDIA_SIZE: {sorted(missing)}")

    def test_no_stray_table_keys(self):
        # A key that is not an enum value is dead weight and hides typos.
        stray = set(xl2hb.PAPER_SIZES) - {s.value for s in PageSize}
        self.assertEqual(stray, set(), f"PAPER_SIZES keys without an enum value: {sorted(stray)}")

    def test_every_size_gets_dimensions(self):
        for size in PageSize:
            with self.subTest(size=size.value):
                width, height = xl2hb.get_image_dimensions(size.value)
                self.assertGreater(width, 0)
                self.assertGreater(height, 0)
                self.assertEqual(width % 32, 0, "image width must be 32-pixel aligned")

    def test_ppd_spellings_resolve_through_the_alias(self):
        # Brother's own PPD spells some groups differently; _missing_ bridges it.
        for spelling in ("B5", "B6", "A5Rotated", "PostCard"):
            with self.subTest(spelling=spelling):
                self.assertIsInstance(PageSize(spelling), PageSize)

    def test_b5_b6_alias_to_iso_sizes(self):
        self.assertIs(PageSize("B5"), PageSize.ISOB5)
        self.assertIs(PageSize("B6"), PageSize.ISOB6)


class PaperPointsTest(unittest.TestCase):
    """The filter renders at exactly the size the PPD advertises."""

    @classmethod
    def setUpClass(cls):
        cls.filter = load_filter()

    def test_paper_points_match_the_ppd(self):
        ppd = ppd_paper_dimensions()
        # Compare through the enum: the filter indexes PAPER_POINTS with the
        # enum value, so "PostCard" in the PPD must find the "Postcard" entry.
        resolved = {PageSize(name).value: wh for name, wh in ppd.items()}
        self.assertEqual(resolved, self.filter.PAPER_POINTS)

    def test_br_a4_long_is_a_real_size(self):
        # 595 x 1148 pt, from Brother's own 3040 PPD.
        self.assertEqual(self.filter.PAPER_POINTS["BrA4Long"], (595, 1148))

    def test_gs_command_uses_the_paperinfij2_size(self):
        # The device must be sized in device pixels from PAPER_SIZES (Brother's
        # paperinfij2), not from the PPD's point size: the point size rounds up
        # (A4 842 pt -> 7017 px) and overshoots Brother's 6981 px by 36 rows.
        for size in PageSize:
            with self.subTest(size=size.value):
                width, height = xl2hb.PAPER_SIZES[size.value]
                cmd = self.filter.build_gs_command("job.ps", size.value)
                self.assertIn(f"-g{width}x{height}", cmd)
                self.assertNotIn("-dDEVICEWIDTHPOINTS", " ".join(cmd))

    def test_gs_command_keeps_brothers_hw_margins(self):
        # Brother's psconvertij2 sets .HWMargins before the job; content near
        # the physical edge only lands correctly with it.
        cmd = self.filter.build_gs_command("job.ps", "A4")
        self.assertIn("<< /HWMargins [12.0 12.0 12.0 12.0] >> setpagedevice", cmd)
        self.assertIn("-f", cmd)


class OtherEnumCoverageTest(unittest.TestCase):
    """Media type and input slot must resolve the same way."""

    def test_media_types_have_strings(self):
        missing = {m.value for m in MediaType} - set(xl2hb.MEDIA_TYPE_STRINGS)
        self.assertEqual(missing, set(), f"media types without a wire string: {sorted(missing)}")

    def test_input_slots_have_codes(self):
        missing = {s.value for s in InputSlot} - set(settings.MEDIA_SOURCE)
        self.assertEqual(missing, set(), f"input slots without a code: {sorted(missing)}")


class PpCapabilityTest(unittest.TestCase):
    """The PPD must not offer what the hardware cannot do."""

    def test_no_duplex_group(self):
        # The HL-3040CN has no duplex unit, and neither has Brother's own PPD.
        text = PPD.read_text(encoding="latin-1")
        self.assertNotIn("*OpenUI *Duplex", text)
        self.assertNotIn("*DefaultDuplex", text)

    def test_page_size_has_page_region(self):
        # cupstestppd warns when PageSize is defined without PageRegion.
        missing = ppd_lines("PageSize") - ppd_lines("PageRegion")
        self.assertEqual(missing, set(), f"PageSize without PageRegion: {sorted(missing)}")


class FilterOptionsTest(unittest.TestCase):
    """Every PPD option group must be one the filter actually reads."""

    @classmethod
    def setUpClass(cls):
        cls.filter = load_filter()
        # The filter itself plus settings.py, which parses the option string.
        cls.sources = FILTER.read_text() + (ROOT / "src" / "settings.py").read_text()

    def test_ppd_options_are_known_to_the_filter(self):
        groups = re.findall(r"^\*OpenUI \*([A-Za-z]+)/", PPD.read_text(encoding="latin-1"), re.M)
        # PageSize/PageRegion are page geometry, handled by name, not options.
        unknown = [
            g for g in groups
            if g not in ("PageSize", "PageRegion") and g not in self.sources
        ]
        self.assertEqual(unknown, [], f"PPD options the filter ignores: {unknown}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
