#!/usr/bin/env python3
"""A4 end-to-end geometry check.

Renders A4 with Ghostscript exactly the way the CUPS filter does and pins
the device size and the position of a known rectangle. This guards the
36-row overshoot: sizing the device from the PPD's point height (842 pt)
gives 7017 px instead of Brother's 6981 px, which shifted every page
1.5 mm down and cut off the bottom rows.

Ghostscript is optional; the raster checks are skipped without it.
"""
import importlib.machinery
import importlib.util
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent
FILTER = ROOT.parent / "cups" / "brhl3040cn-filter"

# A 72x72 pt rectangle at PostScript (72, 720). At 600 dpi with Brother's
# .HWMargins prologue this covers exactly these device rows on A4.
PS = b"%!PS\n0 setgray 72 720 72 72 rectfill\nshowpage\n"
A4_EXPECTED_ROWS = (381, 981)


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


def parse_ppm(data):
    """Parse a binary P6 PPM.

    Returns:
        Tuple of (width, height, pixels) with pixels shaped (height, width, 3).
    """
    idx = 2
    tokens = []
    while len(tokens) < 3:
        while data[idx:idx + 1].isspace():
            idx += 1
        if data[idx:idx + 1] == b"#":
            while data[idx:idx + 1] not in (b"\n", b""):
                idx += 1
            continue
        start = idx
        while not data[idx:idx + 1].isspace():
            idx += 1
        tokens.append(int(data[start:idx]))
    idx += 1
    width, height, _maxval = tokens
    pixels = np.frombuffer(data[idx:idx + width * height * 3], np.uint8)
    return width, height, pixels.reshape(height, width, 3)


def raster_a4():
    """Render the test page on A4 through the filter's own gs command.

    Returns:
        Tuple of (width, height, pixels).

    Raises:
        unittest.SkipTest: If Ghostscript is not installed.
    """
    if shutil.which("gs") is None:
        raise unittest.SkipTest("ghostscript not installed")
    module = load_filter()
    with tempfile.NamedTemporaryFile(suffix=".ps", delete=False) as f:
        f.write(PS)
        ps_path = f.name
    try:
        cmd = module.build_gs_command(ps_path, "A4")
        result = subprocess.run(cmd, capture_output=True, check=True)
    finally:
        Path(ps_path).unlink(missing_ok=True)
    return parse_ppm(result.stdout)


class A4GeometryTest(unittest.TestCase):
    """A4 must rasterise at paperinfij2's size, not the PPD's point size."""

    @classmethod
    def setUpClass(cls):
        cls.filter = load_filter()
        cls.width, cls.height, cls.pixels = raster_a4()

    def test_a4_device_is_4958x6981(self):
        # paperinfij2 says A4 is 4958x6981. The PPD's 595x842 pt would give
        # 4958x7017 through -dDEVICEHEIGHTPOINTS, 36 rows too many.
        self.assertEqual((self.width, self.height), (4958, 6981))

    def test_a4_content_lands_at_the_brother_rows(self):
        dark = self.pixels.min(axis=2) < 128
        rows = np.where(dark.any(axis=1))[0]
        self.assertEqual((int(rows[0]), int(rows[-1])), A4_EXPECTED_ROWS)

    def test_command_sizes_the_device_in_pixels(self):
        cmd = self.filter.build_gs_command("job.ps", "A4")
        self.assertIn("-g4958x6981", cmd)
        self.assertNotIn("-dDEVICEWIDTHPOINTS", " ".join(cmd))

    def test_command_keeps_brothers_hw_margins(self):
        # Content near the physical edge only lands correctly with it.
        cmd = self.filter.build_gs_command("job.ps", "A4")
        self.assertIn("<< /HWMargins [12.0 12.0 12.0 12.0] >> setpagedevice", cmd)


if __name__ == "__main__":
    unittest.main(verbosity=2)
