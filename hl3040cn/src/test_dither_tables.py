#!/usr/bin/env python3
"""Regression tests for the BRCD dither-table loading.

The HL-3040CN ships the cache08 BRCD set. The loader used to look for
cache09 (the HL-4150CDN set), which made every lookup miss and silently
fall back to a 32x32 Bayer matrix. These tests pin the filename and the
real table geometry so that regression cannot come back unnoticed.
"""
import struct
import unittest
from pathlib import Path

import dither

LUT_DIR = Path(__file__).resolve().parent / "lut"
EXPECTED = {"k": (80, 80), "c": (80, 80), "m": (80, 80), "y": (24, 24)}


class BrcdNamingTest(unittest.TestCase):
    def test_cache_suffix_is_cache08(self):
        self.assertEqual(dither._BRCD_CACHE, "cache08")

    def test_built_paths_exist(self):
        for ch in "k c m y".split():
            p = LUT_DIR / f"0600-{ch}_{dither._BRCD_CACHE}.bin"
            self.assertTrue(p.exists(), f"missing {p}")

    def test_lookup_does_not_hardcode_cache09(self):
        # "cache09" may still appear in comments that explain the difference
        # between the 3040 and the 4150 set; the lookup path must not use it.
        src = Path(dither.__file__).read_text()
        code = [
            ln for ln in src.splitlines()
            if "cache09" in ln and not ln.lstrip().startswith("#")
        ]
        self.assertEqual(code, [], f"cache09 still in code: {code}")


class BrcdLoadTest(unittest.TestCase):
    def test_normal_tables_load_with_real_geometry(self):
        t = dither.load_dither_tables(str(LUT_DIR), fine=False, toner_save=False)
        for ch, (w, h) in EXPECTED.items():
            got = (t[ch.upper()].width, t[ch.upper()].height)
            self.assertEqual(got, (w, h), f"channel {ch}: {got} != {(w, h)}")

    def test_toner_save_tables_load(self):
        t = dither.load_dither_tables(str(LUT_DIR), fine=False, toner_save=True)
        self.assertEqual((t["K"].width, t["K"].height), (80, 80))

    def test_never_falls_back_to_bayer(self):
        # A Bayer fallback is 32x32 and shared by all four channels.
        t = dither.load_dither_tables(str(LUT_DIR), fine=False, toner_save=False)
        sizes = {(t[c].width, t[c].height) for c in "KCMY"}
        self.assertNotIn((32, 32), sizes, "silent Bayer fallback is active again")

    def test_y_channel_is_smaller_than_cmy(self):
        # The Y table is 24x24 while K/C/M are 80x80; catching a mix-up here
        # is cheap and it is exactly the kind of swap that hides a bad load.
        t = dither.load_dither_tables(str(LUT_DIR), fine=False, toner_save=False)
        self.assertNotEqual((t["Y"].width, t["Y"].height), (t["K"].width, t["K"].height))


class BrcdHeaderTest(unittest.TestCase):
    def test_headers_agree_with_loader(self):
        for ch, (w, h) in EXPECTED.items():
            raw = (LUT_DIR / f"0600-{ch}_{dither._BRCD_CACHE}.bin").read_bytes()
            self.assertEqual(raw[:4], b"BRCD")
            fw, fh = struct.unpack("<HH", raw[6:10])
            self.assertEqual((fw, fh), (w, h), f"{ch}: header {(fw, fh)}")
            # 256 patterns of ceil(w*h/8) bytes plus a 10-byte header.
            self.assertEqual(len(raw), 10 + 256 * ((w * h + 7) // 8))

    def test_threshold_matrix_is_uint8(self):
        ch = dither.dither_load_brcd(str(LUT_DIR / "0600-y_cache08.bin"))
        self.assertEqual(ch.threshold_matrix.dtype.name, "uint8")
        self.assertEqual(ch.threshold_matrix.shape, (24, 24))


if __name__ == "__main__":
    unittest.main(verbosity=2)
