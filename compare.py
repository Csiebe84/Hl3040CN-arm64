#!/usr/bin/env python3
"""Compare the native HL-3040CN filter against Brother's binary, byte for byte.

The proprietary filter runs in the `brother-cups` container; this script feeds
both it and the native pipeline the same PPM and reports whether the XL2HB
sessions they produce are identical, and if not, where they first diverge.
"""

from __future__ import annotations

import io
import subprocess
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent / "hl3040cn" / "src"
sys.path.insert(0, str(SRC))

from pipeline import filter_page  # noqa: E402
from ppm import read_ppm  # noqa: E402
from settings import ColorMatching, MonoColor, PrintSettings, Resolution  # noqa: E402

CONTAINER = "brother-cups"
PRINTER = "/opt/brother/Printers/hl3040cn"
FILTER = f"{PRINTER}/lpd/brhl3040cnfilter"
PAPER_INF = f"{PRINTER}/inf/paperinfij2"
RC = f"{PRINTER}/inf/brhl3040cnrc"
SESSION_MARKER = b") BROTHER XL2HB;1;0\n"


def ppm(width: int, height: int, pixel_fn) -> bytes:
    """Build a P6 PPM whose rows come from `pixel_fn(y) -> bytes`."""
    body = bytearray()
    for y in range(height):
        body += pixel_fn(y)
    return b"P6\n%d %d\n255\n" % (width, height) + bytes(body)


def oracle_rc(settings: PrintSettings) -> str:
    """Render an rc file for the oracle from the same settings the port uses.

    The container's own rc is edited by hand for other experiments, so reading
    it would make this comparison depend on whatever was last written there.
    Deriving it from `settings` keeps both sides on the same page size and
    colour mode.
    """
    return "\n".join([
        "[HL3040CN]",
        f"MediaType={settings.media_type}",
        f"PageSize={settings.page_size}",
        f"InputSlot={settings.input_slot}",
        f"BRResolution={settings.resolution}",
        f"Copies={settings.copies}",
        "BRReverse=OFF",
        f"BRMonoColor={settings.mono_color}",
        f"BRColorMatching={settings.color_matching}",
        f"BRGray={'ON' if settings.improve_gray else 'OFF'}",
        f"BREnhanceBlkPrt={'ON' if settings.enhance_black else 'OFF'}",
        f"TonerSaveMode={'ON' if settings.toner_save else 'OFF'}",
        f"BRImproveOutput={settings.improve_output}",
        f"Brightness={settings.brightness}",
        f"Contrast={settings.contrast}",
        f"RedKey={settings.red}",
        f"GreenKey={settings.green}",
        f"BlueKey={settings.blue}",
        f"Saturation={settings.saturation}",
        "Language=us",
        "",
    ])


def oracle(data: bytes, settings: PrintSettings) -> bytes:
    """Run Brother's filter over a PPM with settings-matched rc, return output."""
    subprocess.run(
        ["docker", "exec", "-i", CONTAINER, "sh", "-c", "cat > /tmp/compare.rc"],
        input=oracle_rc(settings).encode(), check=True,
    )
    return subprocess.run(
        ["docker", "exec", "-i", CONTAINER, "sh", "-c",
         f"{FILTER} -pi {PAPER_INF} -rc /tmp/compare.rc"],
        input=data, capture_output=True, check=False,
    ).stdout


def native(data: bytes, width: int, height: int, settings: PrintSettings) -> bytes:
    """Run the native pipeline over a PPM and return its output."""
    parsed = read_ppm(io.BytesIO(data))
    if parsed is None:
        return b""
    pw, ph, _maxval, pixels = parsed
    out = io.BytesIO()
    filter_page(pw, ph, pixels, settings, out)
    return out.getvalue()


def session(stream: bytes) -> bytes:
    """Return the part from the XL2HB session marker onwards.

    The bytes before it are CUPS job metadata that only the container wrapper
    adds, so they are not part of what the driver must reproduce.
    """
    at = stream.find(SESSION_MARKER)
    return stream[at:] if at >= 0 else stream


def compare(name: str, data: bytes, width: int, height: int, settings: PrintSettings) -> bool:
    """Report whether native output matches the oracle for one page."""
    want = session(oracle(data, settings))
    got = session(native(data, width, height, settings))
    if want == got:
        print(f"  {name:28s} OK      {len(got):7d} bytes identical")
        return True
    print(f"  {name:28s} DIFF    oracle={len(want)} native={len(got)}")
    limit = min(len(want), len(got))
    at = next((i for i in range(limit) if want[i] != got[i]), limit)
    print(f"      first difference at offset {at}")
    print(f"      oracle: {want[max(0, at - 8) : at + 24].hex()}")
    print(f"      native: {got[max(0, at - 8) : at + 24].hex()}")
    return False


def main() -> None:
    """Run the pattern set through both filters and summarise."""
    width, height = 5100, 6564
    solid = lambda rgb: (lambda y: bytes(rgb) * width)  # noqa: E731
    bar = lambda rgb, x0, x1: (  # noqa: E731
        lambda y: bytes((255, 255, 255)) * x0
        + bytes(rgb) * (x1 - x0)
        + bytes((255, 255, 255)) * (width - x1)
    )
    cases = [
        ("black solid", solid((0, 0, 0))),
        ("white solid", solid((255, 255, 255))),
        ("red solid", solid((255, 0, 0))),
        ("green solid", solid((0, 255, 0))),
        ("blue solid", solid((0, 0, 255))),
        ("cyan solid", solid((0, 255, 255))),
        ("magenta solid", solid((255, 0, 255))),
        ("yellow solid", solid((255, 255, 0))),
        ("grey 50%", solid((128, 128, 128))),
        ("black bar 100px", bar((0, 0, 0), 1000, 1100)),
        ("black bar 300px", bar((0, 0, 0), 2000, 2300)),
        ("red bar 300px", bar((255, 0, 0), 1000, 1300)),
    ]

    settings = PrintSettings()
    settings.page_size = "Letter"
    print("Native vs Brother HL-3040CN filter (Letter, Normal colour):")
    results = [compare(name, ppm(width, height, fn), width, height, settings) for name, fn in cases]
    print(f"\n{sum(results)}/{len(results)} patterns byte-identical")


if __name__ == "__main__":
    main()
