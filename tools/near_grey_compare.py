#!/usr/bin/env python3
"""Near-achromatic comparison: the sensitive test the 12-case suite misses.

`compare_extended.py` uses pure greys (R=G=B) and saturated colours, so it
cannot tell the exact rule (`R==G==B`) from a tolerance-based one. This script
uses colours that sit just off the grey axis, where the two rules disagree, and
compares each against Brother's filter.

Usage:
    tools/near_grey_compare.py            # the working tree's color_lut
    tools/near_grey_compare.py --base     # the committed color_lut (HEAD)

The `--base` mode injects the committed module, so it measures the same thing
the repository ships. Use it to prove a change actually moves a case.
"""
from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent

# Colours chosen so the two rules disagree. (16,0,0) and (5,5,5) are controls
# that already matched; the rest are the sensitive ones.
COLOURS = [
    (16, 0, 0), (5, 5, 5), (255, 255, 254),          # controls: already OK
    (20, 5, 5), (100, 84, 84), (60, 40, 40),          # small, one-sided offsets
    (128, 128, 120), (200, 190, 180), (240, 240, 230),  # light near-greys
    (0, 0, 1), (50, 48, 45), (90, 80, 70),            # 1-5 unit offsets
]


def use_committed_color_lut() -> None:
    """Load HEAD's color_lut.py before compare does, and pin it in sys.modules."""
    blob = subprocess.run(
        ["git", "-C", str(ROOT), "show", "HEAD:hl3040cn/src/color_lut.py"],
        capture_output=True, check=True,
    ).stdout
    tmp = Path("/mnt/ssd/finecmp/_committed_color_lut.py")
    tmp.parent.mkdir(parents=True, exist_ok=True)
    tmp.write_bytes(blob)
    sys.path.insert(0, str(ROOT / "hl3040cn" / "src"))  # for _compat & siblings
    spec = importlib.util.spec_from_file_location("color_lut", tmp)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["color_lut"] = mod
    spec.loader.exec_module(mod)
    print(f"# color_lut: HEAD (committed)\n", flush=True)


def main() -> None:
    if "--base" in sys.argv:
        use_committed_color_lut()
    else:
        print("# color_lut: working tree\n", flush=True)
    sys.path.insert(0, str(ROOT))

    import compare  # noqa: E402
    from settings import PrintSettings  # noqa: E402

    w, h = 5100, 6564
    settings = PrintSettings()
    settings.page_size = "Letter"
    settings.improve_gray = False

    same = 0
    for rgb in COLOURS:
        def row(_y: int, rgb=rgb) -> bytes:
            return bytes(rgb) * w
        if compare.compare(f"{rgb}", compare.ppm(w, h, row), w, h, settings):
            same += 1
    print(f"\n{same}/{len(COLOURS)} byte-identical")


if __name__ == "__main__":
    main()
