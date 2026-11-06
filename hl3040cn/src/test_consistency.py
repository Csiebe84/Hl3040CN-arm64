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
import subprocess
import unittest
from pathlib import Path

import settings
import xl2hb
from settings import InputSlot, MediaType, PageSize, PrintSettings, Resolution

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


class DefaultMediaTest(unittest.TestCase):
    """The default page size must agree with CUPS' media-ready list.

    cupsd picks `media-ready` from its `ReadyPaperSizes` array, which is derived
    from `DefaultPaperSize`. That is auto-detected from the locale (A4 for
    de_DE), so on this A4-only printer the ready list is A4,A5,DL,A6. A PPD
    default of Letter then advertises `media-default=na_letter_8.5x11in`, a size
    the queue never reports as loaded -- Mopria/AirPrint clients drop such a
    printer from the discovery list. Both default keywords must name a size that
    is in the PPD's own `media-ready` family, i.e. A4 here.
    """

    def ppd_default(self, keyword):
        """Value of one `*Default<keyword>:` line."""
        match = re.search(rf"^\*Default{keyword}:\s*(\S+)", PPD.read_text(encoding="latin-1"), re.M)
        self.assertIsNotNone(match, f"*Default{keyword} is missing from the PPD")
        return match.group(1)

    def test_default_page_size_is_a4(self):
        # The printer is sold and used in Germany; Letter is not loaded in it.
        self.assertEqual(self.ppd_default("PageSize"), "A4")

    def test_imageable_area_and_paper_dimension_follow(self):
        # All four default keywords must agree, or cupstestppd flags a mismatch.
        self.assertEqual(self.ppd_default("ImageableArea"), "A4")
        self.assertEqual(self.ppd_default("PaperDimension"), "A4")

    def test_page_region_follows_the_page_size(self):
        # PageRegion is the fourth geometry default and was the one left behind
        # when the others were moved to A4: PageSize said A4 while PageRegion
        # still said Letter. cupstestppd accepts that, so only this test catches
        # it -- and the queue then resolves the region to Letter at job time.
        self.assertEqual(self.ppd_default("PageRegion"), "A4")

    def test_all_geometry_defaults_agree(self):
        # One list so a future edit cannot move three of the four again.
        values = {
            keyword: self.ppd_default(keyword)
            for keyword in ("PageSize", "PageRegion", "ImageableArea", "PaperDimension")
        }
        self.assertEqual(set(values.values()), {"A4"}, f"geometry defaults disagree: {values}")

    def test_default_is_in_the_cups_ready_list(self):
        # CUPS builds ReadyPaperSizes from the locale (A4 for de_DE) as
        # "A4,A3,A5,A6,EnvDL". A4 must be one of them, or media-default would
        # name a size the queue never advertises as ready.
        self.assertIn(self.ppd_default("PageSize"), {"A4", "A3", "A5", "A6", "EnvDL"})


class InstalledPpdTest(unittest.TestCase):
    """The copy install.sh ships must match the one in the repository.

    install.sh copies cups/brhl3040cn.ppd to /usr/share/cups/model/ and builds
    the queue from that copy. Fixing only the repository file therefore leaves
    the installed queue on the old values -- which is exactly how the Letter
    default survived a fix that had already landed: the repository PPD was
    corrected, the installed copy was not. Skipped where CUPS is absent, so the
    suite still runs on a machine without it.
    """

    INSTALLED = Path("/usr/share/cups/model/brhl3040cn.ppd")

    def setUp(self):
        if not self.INSTALLED.exists():
            self.skipTest("no installed model PPD on this machine")

    def geometry_defaults(self, path):
        text = path.read_text(encoding="latin-1")
        return {
            keyword: re.search(rf"^\*Default{keyword}:\s*(\S+)", text, re.M).group(1)
            for keyword in ("PageSize", "PageRegion", "ImageableArea", "PaperDimension")
        }

    def test_installed_ppd_matches_the_repository(self):
        self.assertEqual(
            self.geometry_defaults(self.INSTALLED),
            self.geometry_defaults(PPD),
            "the installed model PPD is out of step with cups/brhl3040cn.ppd",
        )


class CupsCertificateTest(unittest.TestCase):
    """cupsd must not serve a certificate the local CA did not sign.

    cupsd writes itself a self-signed certificate into /etc/cups/ssl/<host>.crt
    when none is present, and it happily keeps serving that one. A client that
    trusts only the local CA -- Android on the IPPS path -- then aborts the
    connection, while HTTPS stays healthy because nginx has a proper leaf. The
    failure is invisible in `systemctl is-active cups`, so it needs a test.

    Skipped wherever CUPS or the local CA is absent.
    """

    CUPS_CERT = Path("/etc/cups/ssl/odroidn2.crt")
    CA_CERT = Path("/etc/nginx/ssl/ca.crt")

    def setUp(self):
        for path in (self.CUPS_CERT, self.CA_CERT):
            if not path.exists():
                self.skipTest(f"{path} not present on this machine")

    def openssl(self, *args):
        return subprocess.run(
            ["openssl", *args], capture_output=True, text=True, timeout=30
        )

    def test_certificate_is_signed_by_the_local_ca(self):
        issuer = self.openssl("x509", "-in", str(self.CUPS_CERT), "-noout", "-issuer")
        subject = self.openssl("x509", "-in", str(self.CUPS_CERT), "-noout", "-subject")
        self.assertNotEqual(
            issuer.stdout.strip().removeprefix("issuer="),
            subject.stdout.strip().removeprefix("subject="),
            "the CUPS certificate is self-signed; IPPS clients that trust only "
            "the local CA will reject it",
        )

    def test_certificate_chain_verifies_against_the_local_ca(self):
        # The leaf is stored with the CA appended, so -untrusted supplies the
        # chain for a client that does not hold the CA itself.
        result = self.openssl(
            "verify",
            "-CAfile",
            str(self.CA_CERT),
            "-untrusted",
            str(self.CUPS_CERT),
            str(self.CUPS_CERT),
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_certificate_covers_the_lan_address(self):
        text = self.openssl(
            "x509", "-in", str(self.CUPS_CERT), "-noout", "-ext", "subjectAltName"
        ).stdout
        addresses = re.findall(r"IP Address:(\S+)", text)
        self.assertTrue(
            any(addr.startswith("192.168.178.") for addr in addresses),
            f"the CUPS certificate has no LAN IP SAN, so IPPS by address cannot "
            f"match it (found: {addresses})",
        )


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
        # cupsPrintQuality/Resolution are standard IPP job attributes that CUPS
        # hands to the filter verbatim, so they need no name in the sources.
        standard = ("PageSize", "PageRegion", "cupsPrintQuality", "Resolution")
        unknown = [
            g for g in groups
            if g not in standard and g not in self.sources
        ]
        self.assertEqual(unknown, [], f"PPD options the filter ignores: {unknown}")

    def test_ppd_exposes_standard_quality_options(self):
        """Driverless clients can only select quality via standard IPP attributes."""
        text = PPD.read_text(encoding="latin-1")
        self.assertIn("*OpenUI *cupsPrintQuality/", text)
        self.assertIn("*OpenUI *Resolution/", text)
        self.assertIn("*cupsPrintQuality High/", text)
        self.assertIn("*Resolution 600x2400dpi/", text)


class StandardQualityMappingTest(unittest.TestCase):
    """A driverless job's quality attribute must reach Fine, not just Normal."""

    def test_print_quality_maps_to_resolution(self):
        # IPP print-quality: 3=draft, 4=normal, 5=high.
        for value, expected in (("3", Resolution.NORMAL), ("4", Resolution.NORMAL), ("5", Resolution.FINE)):
            s = PrintSettings.from_cups_options(f"print-quality={value}", 1, {})
            self.assertEqual(s.resolution, expected, f"print-quality={value}")

    def test_cups_print_quality_maps_to_resolution(self):
        for value, expected in (("Draft", Resolution.NORMAL), ("Normal", Resolution.NORMAL), ("High", Resolution.FINE)):
            s = PrintSettings.from_cups_options(f"cupsPrintQuality={value}", 1, {})
            self.assertEqual(s.resolution, expected, f"cupsPrintQuality={value}")

    def test_printer_resolution_maps_to_resolution(self):
        self.assertEqual(
            PrintSettings.from_cups_options("Resolution=600x2400dpi", 1, {}).resolution, Resolution.FINE
        )
        self.assertEqual(
            PrintSettings.from_cups_options("Resolution=600dpi", 1, {}).resolution, Resolution.NORMAL
        )

    def test_ipp_printer_resolution_maps_to_resolution(self):
        # CUPS passes the raw IPP attribute through as "printer-resolution".
        self.assertEqual(
            PrintSettings.from_cups_options("printer-resolution=600x2400dpi", 1, {}).resolution, Resolution.FINE
        )
        self.assertEqual(
            PrintSettings.from_cups_options("printer-resolution=600dpi", 1, {}).resolution, Resolution.NORMAL
        )

    def test_quality_beats_incidental_resolution(self):
        # A driverless client may send a resolution next to the quality it chose.
        s = PrintSettings.from_cups_options(
            "print-quality=5 cupsPrintQuality=High printer-resolution=600dpi", 1, {}
        )
        self.assertEqual(s.resolution, Resolution.FINE)

    def test_brother_option_wins_over_standard(self):
        s = PrintSettings.from_cups_options("print-quality=5 BRResolution=600dpi", 1, {})
        self.assertEqual(s.resolution, Resolution.NORMAL)
        s = PrintSettings.from_cups_options("print-quality=4 BRResolution=600x2400dpi", 1, {})
        self.assertEqual(s.resolution, Resolution.FINE)


if __name__ == "__main__":
    unittest.main(verbosity=2)
