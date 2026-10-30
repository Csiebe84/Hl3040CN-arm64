#!/usr/bin/env python3
"""Which grid does the oracle's gray=OFF page use? Byte-compare per candidate."""
from __future__ import annotations

import io
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "src"))
sys.path.insert(0, str(HERE.parent / "hl3040cn" / "src"))

import color_lut  # noqa: E402
import pipeline  # noqa: E402
from pipeline import filter_page  # noqa: E402
from ppm import read_ppm  # noqa: E402
from ramp_pipeline_compare import session  # noqa: E402
from settings import ColorMatching, PrintSettings  # noqa: E402

pipeline.HAS_BAND_KERNEL = False
FIX = Path("/mnt/ssd/bprobe")
SW, HEIGHT = 5100, 6564
MATCH = {"Normal": ColorMatching.NORMAL, "Vivid": ColorMatching.VIVID}


def bars_ppm(colors):
    step = SW // len(colors)
    row = bytearray()
    for c in colors:
        row += bytes(c) * step
    row += bytes(colors[-1]) * (SW - len(row) // 3)
    return b"P6\n%d %d\n255\n" % (SW, HEIGHT) + bytes(row) * HEIGHT


def main() -> int:
    matching = sys.argv[sys.argv.index("--matching") + 1] if "--matching" in sys.argv else "Normal"
    colors = []
    for line in Path(sys.argv[1]).read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            colors.append(tuple(int(x) for x in line.split()))
    st = PrintSettings()
    st.page_size = "Letter"
    st.color_matching = MATCH[matching]
    st.improve_gray = False
    ppm = bars_ppm(colors)
    (FIX / "wh.ppm").write_bytes(ppm)
    subprocess.run([sys.executable, str(HERE / "oracle_run.py"), str(FIX / "wh.ppm"),
                    "/tmp/wh.xl2hb", "--matching", matching, "--gray", "OFF"],
                   check=True, capture_output=True)
    oracle = session(Path("/tmp/wh.xl2hb").read_bytes())
    cands = [color_lut.ColorTable(p, ig, v) for p in ("rgb", "srgb", "cmyk")
             for ig in (False, True) for v in ("default", "density2", "glossy")]
    cands.append(color_lut.ColorTable("rgb" if matching == "Normal" else "srgb",
                                      improve_gray=True, gray_replace=True))
    cands.append(color_lut.ColorTable("rgb" if matching == "Normal" else "srgb",
                                      improve_gray=False, gray_replace=True))
    w, h, _m, px = read_ppm(io.BytesIO(ppm))
    for g in cands:
        orig = pipeline.color_table
        pipeline.color_table = lambda _s, _g=g: _g
        try:
            o = io.BytesIO()
            filter_page(w, h, px, st, o)
            out = session(o.getvalue())
        finally:
            pipeline.color_table = orig
        n = min(len(out), len(oracle))
        d = sum(1 for i in range(n) if out[i] != oracle[i]) + abs(len(out) - len(oracle))
        first = next((i for i in range(n) if out[i] != oracle[i]), None)
        print(f"{g.name:24s} diff={d} first={first} len={len(out)}/{len(oracle)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
