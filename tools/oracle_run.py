#!/usr/bin/env python3
"""Run the oracle filter with custom colour settings.

`ramp_build.py` always uses the printer's default rc, which cannot answer
"which grid does BRColorMatching=Vivid / BRGray=OFF select?".  This tool writes
a temporary rc into the container and pushes a PPM through the filter, so the
grid naming can be pinned by varying one setting at a time.

Usage: oracle_run.py <ppm> <out.xl2hb> [--matching Normal|Vivid|None] [--gray ON|OFF]
                               [--resolution Normal|Fine]
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

CONTAINER = "brother-cups"
PRINTER = "/opt/brother/Printers/hl3040cn"
FILTER = f"{PRINTER}/lpd/brhl3040cnfilter"
RC_TEMPLATE = """[HL3040CN]
MediaType={media}
PageSize={page}
InputSlot=AutoSelect
BRResolution={resolution}
Copies=1
BRReverse=OFF
BRMonoColor=Auto
BRColorMatching={matching}
BRGray={gray}
BREnhanceBlkPrt={enhance}
TonerSaveMode={toner}
BRImproveOutput=OFF
Brightness=0
Contrast=0
RedKey=0
GreenKey=0
BlueKey=0
Saturation=0
Language=us
"""


def main() -> int:
    """Run the filter with the requested settings and store its output."""
    args = sys.argv[1:]
    opts = {"matching": "Normal", "gray": "ON", "toner": "OFF", "media": "Plain", "enhance": "OFF", "resolution": "Normal", "page": "Letter"}
    for key in opts:
        flag = f"--{key}"
        if flag in args:
            opts[key] = args[args.index(flag) + 1]
    ppm_path, out_path = Path(args[0]), Path(args[1])
    rc = RC_TEMPLATE.format(**opts)
    subprocess.run(
        ["docker", "exec", "-i", CONTAINER, "sh", "-c", "cat > /tmp/oracle_run.rc"],
        input=rc.encode(), check=True,
    )
    result = subprocess.run(
        ["docker", "exec", "-i", CONTAINER, "sh", "-c",
         f"{FILTER} -pi {PRINTER}/inf/paperinfij2 -rc /tmp/oracle_run.rc"],
        input=ppm_path.read_bytes(), capture_output=True, check=False,
    )
    out_path.write_bytes(result.stdout)
    print(" ".join(f"{k}={v}" for k, v in opts.items()) + f" -> {out_path} ({len(result.stdout)} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
