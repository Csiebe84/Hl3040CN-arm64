#!/usr/bin/env python3
"""Drive Brother's i386 filter in the container and pull captures back.

The container is the oracle: it answers "what bytes should these pixels
produce" for the HL-3040CN.  Everything here talks to it through `docker exec`
and keeps the captures in ref/oracle/ so the native driver can be checked
against them without the emulator.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

CONTAINER = "brother-cups"
PRINTER = "/opt/brother/Printers/hl3040cn"
RC = f"{PRINTER}/inf/brhl3040cnrc"
FILTER = f"{PRINTER}/lpd/filterhl3040cn"
OUT_DIR = Path(__file__).resolve().parent.parent / "ref" / "oracle"

# The rc file keys the driver reads for each job; the wrapper rewrites it per
# queue in real use, so the oracle is steered the same way.
RC_KEYS = {
    "MediaType": "MediaType",
    "PageSize": "PageSize",
    "InputSlot": "InputSlot",
    "Resolution": "BRResolution",
    "MonoColor": "BRMonoColor",
    "ColorMatching": "BRColorMatching",
    "Gray": "BRGray",
    "EnhanceBlack": "BREnhanceBlkPrt",
    "TonerSave": "TonerSaveMode",
    "ImproveOutput": "BRImproveOutput",
    "Brightness": "Brightness",
    "Contrast": "Contrast",
    "RedKey": "RedKey",
    "GreenKey": "GreenKey",
    "BlueKey": "BlueKey",
    "Saturation": "Saturation",
    "Reverse": "BRReverse",
}


def run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    """Run a command, raising on failure unless `check=False`."""
    return subprocess.run(cmd, capture_output=True, check=kw.pop("check", True), **kw)


def set_rc(**values: str) -> None:
    """Set rc-file keys in the container.

    Args:
        **values: `RC_KEYS` names to values, e.g. ``PageSize="A4"``.
    """
    for name, value in values.items():
        key = RC_KEYS[name]
        script = f"sed -i 's|^{key}=.*|{key}={value}|' {RC}"
        run(["docker", "exec", CONTAINER, "sh", "-c", script])


def read_rc() -> str:
    """Return the container's current rc file."""
    return run(["docker", "exec", CONTAINER, "cat", RC]).stdout.decode()


def restore_rc(original: str) -> None:
    """Write `original` back as the rc file."""
    proc = subprocess.run(
        ["docker", "exec", "-i", CONTAINER, "sh", "-c", f"cat > {RC}"],
        input=original.encode(),
        capture_output=True,
        check=True,
    )
    assert proc.returncode == 0


def filter_ps(ps: bytes) -> bytes:
    """Push PostScript through the container's filter and return the stream."""
    proc = subprocess.run(
        ["docker", "exec", "-i", CONTAINER, "sh", "-c", f"{FILTER} 1 CUPS USB"],
        input=ps,
        capture_output=True,
        check=True,
    )
    return proc.stdout


def capture(name: str, ps: bytes, **rc) -> bytes:
    """Filter `ps` with the given rc settings and save the result.

    Args:
        name: Output file stem under ref/oracle/.
        ps: The PostScript job.
        **rc: rc-file settings to apply for this capture.

    Returns:
        The raw XL2HB stream.
    """
    original = read_rc()
    try:
        if rc:
            set_rc(**rc)
        data = filter_ps(ps)
    finally:
        restore_rc(original)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / f"{name}.xl2hb").write_bytes(data)
    return data


def main() -> None:
    """Capture a small probe page for every paper size."""
    from pclxl import parse

    sizes = [
        "A4", "Letter", "Legal", "Executive", "A5", "PRA5Rotated", "A6", "B5", "B6",
        "JISB5", "JISB6", "EnvDL", "EnvC5", "Env10", "EnvMonarch", "Br3x5",
        "BrA4Long", "FanFoldGermanLegal", "EnvPRC5Rotated", "PostCard", "EnvYou4",
        "EnvChou3",
    ]
    # A single black mark so at least one block is emitted.
    ps = b"%!PS\n0 setgray 72 720 72 72 rectfill\nshowpage\n"
    for size in sizes:
        try:
            data = capture(f"geom_{size}", ps, PageSize=size)
        except subprocess.CalledProcessError as exc:
            print(f"{size}: filter failed: {exc.stderr.decode()[:200]}", file=sys.stderr)
            continue
        ops = parse(data)
        img = next(o for o in ops if o.name == "BeginImage")
        blocks = [o for o in ops if o.name == "ReadImage"]
        print(
            f"{size:20s} src={img.attrs['SourceWidth']}x{img.attrs['SourceHeight']} "
            f"blocks={len(blocks)}"
        )


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    main()
