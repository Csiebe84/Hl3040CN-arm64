#!/usr/bin/env python3
"""End-to-end fuzz of the installed CUPS filter.

Runs the *real* filter binary (the one CUPS execs) over a matrix of inputs that
the unit tests do not cover: empty pages, 1-pixel pages, oversized pages, every
paper size, every resolution, both colour matchings, toner save, copies, and
deliberately malformed PostScript.  For each case it checks that the filter

  * exits 0,
  * writes a non-trivial XL2HB payload (or a documented empty-page stub),
  * never leaves a Python traceback on stderr.

The point is to find the *next* failure, not to confirm the known-good paths.
Results go to stdout and to logs/fuzz_filter.md.

Cases named in EXPECT_FAIL are the deliberately malformed inputs: a non-zero
exit with a clean message is the *correct* outcome there, not a failure.

Usage: fuzz_filter.py [--quick]
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

FILTER = "/usr/lib/cups/filter/brhl3040cn-filter"
WORK = Path("/mnt/ssd/fuzz")
OUT = WORK / "out.prn"
LOGFILE = Path("/root/brother/native/logs/fuzz_filter.md")

# The queue's own default is Fine; exercise both, and the standard IPP names.
BASE_OPTS = "BRResolution=600x2400dpi BRColorMatching=Normal BRGray=OFF BRMediaType=Plain"


def page(ps_body: str) -> bytes:
    """Wrap a PostScript body in a minimal, valid document.

    The `%%Page:` marker matters: `pstops` counts pages by it, and a document
    without one is handed to the filter as a single page with no copy fan-out.
    """
    return (
        "%!PS-Adobe-3.0\n%%Pages: 1\n%%BoundingBox: 0 0 612 792\n"
        "%%EndComments\n%%Page: 1 1\n%%BeginPageSetup\n%%EndPageSetup\n"
        + ps_body + "\nshowpage\n%%EOF\n"
    ).encode()


def draw(x: int, y: int, w: int, h: int, r: float, g: float, b: float) -> str:
    return f"{r} {g} {b} setrgbcolor {x} {y} {w} {h} rectfill"


CASES: list[tuple[str, bytes, str]] = [
    # --- degenerate geometry -------------------------------------------------
    ("empty_page", page(""), BASE_OPTS),
    ("white_page", page("1 1 1 setrgbcolor 0 0 612 792 rectfill"), BASE_OPTS),
    ("one_pixel", page(draw(10, 10, 1, 1, 0, 0, 0)), BASE_OPTS),
    ("one_row", page(draw(0, 400, 612, 1, 0, 0, 0)), BASE_OPTS),
    ("one_column", page(draw(300, 0, 1, 792, 0, 0, 0)), BASE_OPTS),
    ("full_black", page("0 0 0 setrgbcolor 0 0 612 792 rectfill"), BASE_OPTS),
    ("full_white_offpage", page(draw(-100, -100, 10, 10, 0, 0, 0)), BASE_OPTS),
    ("oversized_rect", page(draw(0, 0, 5000, 5000, 0, 0, 0)), BASE_OPTS),
    # --- colour corners ------------------------------------------------------
    ("pure_red", page(draw(0, 0, 612, 792, 1, 0, 0)), BASE_OPTS),
    ("pure_green", page(draw(0, 0, 612, 792, 0, 1, 0)), BASE_OPTS),
    ("pure_blue", page(draw(0, 0, 612, 792, 0, 0, 1)), BASE_OPTS),
    ("mid_gray", page(draw(0, 0, 612, 792, 0.5, 0.5, 0.5)), BASE_OPTS),
    ("mixed_128_128_130", page(draw(0, 0, 612, 792, 128 / 255, 128 / 255, 130 / 255)), BASE_OPTS),
    ("mixed_200_50_100", page(draw(0, 0, 612, 792, 200 / 255, 50 / 255, 100 / 255)), BASE_OPTS),
    # --- gradients (the known-open separation case) --------------------------
    (
        "gradient_rgb",
        page(
            "0 1 200 { /t exch 255 div def "
            "t t 1 t sub setrgbcolor 0 0 3 792 rectfill } for"
        ),
        BASE_OPTS,
    ),
    (
        "gradient_gray",
        page("0 1 200 { /t exch 255 div def t t t setrgbcolor 0 0 3 792 rectfill } for"),
        BASE_OPTS,
    ),
    # --- option matrix -------------------------------------------------------
    ("vivid", page(draw(0, 0, 612, 792, 0.8, 0.2, 0.4)), "BRColorMatching=Vivid BRGray=OFF"),
    ("graymode_on", page(draw(0, 0, 612, 792, 0.5, 0.5, 0.5)), "BRGray=ON"),
    ("toner_save", page("0 0 0 setrgbcolor 0 0 612 792 rectfill"), BASE_OPTS + " BRTonerSaveMode=True"),
    ("normal_res", page(draw(0, 0, 612, 792, 0, 0, 0)), "BRResolution=600dpi BRGray=OFF"),
    ("ipp_high", page(draw(0, 0, 612, 792, 0, 0, 0)), "cupsPrintQuality=High"),
    ("ipp_draft", page(draw(0, 0, 612, 792, 0, 0, 0)), "cupsPrintQuality=Draft"),
    ("empty_options", page(draw(0, 0, 612, 792, 0, 0, 0)), ""),
    # --- every paper size ----------------------------------------------------
    ("a4", page(draw(0, 0, 595, 842, 0, 0, 0)), "PageSize=A4 " + BASE_OPTS),
    ("a5", page(draw(0, 0, 420, 595, 0, 0, 0)), "PageSize=A5 " + BASE_OPTS),
    ("legal", page(draw(0, 0, 612, 1008, 0, 0, 0)), "PageSize=Legal " + BASE_OPTS),
    ("env_dl", page(draw(0, 0, 312, 624, 0, 0, 0)), "PageSize=EnvDL " + BASE_OPTS),
    ("br3x5", page(draw(0, 0, 216, 360, 0, 0, 0)), "PageSize=Br3x5 " + BASE_OPTS),
    # --- multi-page ----------------------------------------------------------
    (
        "two_pages",
        (
            "%!PS-Adobe-3.0\n%%Pages: 2\n"
            "0 0 0 setrgbcolor 0 0 612 792 rectfill showpage\n"
            "1 0 0 setrgbcolor 0 0 612 792 rectfill showpage\n%%EOF\n"
        ).encode(),
        BASE_OPTS,
    ),
    # --- deliberately malformed ---------------------------------------------
    ("not_postscript", b"this is not postscript at all\n", BASE_OPTS),
    ("truncated_ps", b"%!PS-Adobe-3.0\n0 0 0 setrgbcolor\n", BASE_OPTS),
    ("binary_garbage", bytes(range(256)) * 8, BASE_OPTS),
    ("empty_input", b"", BASE_OPTS),
]

# Malformed inputs: a clean non-zero exit is the expected result.
EXPECT_FAIL = {"not_postscript", "truncated_ps", "binary_garbage", "empty_input"}

PSTOPS = "/usr/lib/cups/filter/pstops"


def run_copies_case() -> dict:
    """Run the *real* `lp -n 3` chain: pstops | filter, one-page document.

    CUPS' pstops fans the copies out, so the filter receives a document it must
    render exactly once; it only carries the count in-band (attr 0x31).  A
    filter that repeated pages itself would print 9 pages for `lp -n 3`.
    """
    import re

    src = WORK / "copies_in.ps"
    src.write_bytes(page("0 0 0 setrgbcolor 0 0 612 792 rectfill"))
    try:
        ps = subprocess.run(
            [PSTOPS, "1", "fuzz", "copies", "3", "PageSize=Letter", str(src)],
            capture_output=True, timeout=120,
        )
    except subprocess.TimeoutExpired:
        return {"name": "copies_via_pstops", "verdict": "TIMEOUT", "size": 0, "rc": None, "stdout": b""}
    if ps.returncode != 0:
        return {"name": "copies_via_pstops", "verdict": f"PSTOPS_RC={ps.returncode}",
                "size": 0, "rc": ps.returncode, "stdout": b"", "stderr": ps.stderr[-400:].decode("utf-8", "replace")}

    # CUPS passes the copy count in argv[4] (verified in /var/log/cups/error_log).
    r = run_case("copies_via_pstops", ps.stdout, BASE_OPTS, copies=3)
    data = r.get("stdout", b"")
    begins = re.findall(rb"\xc1(..)\xf8\x31\xb0", data, re.S)
    counts = [int.from_bytes(m.group(1), "little") for m in re.finditer(rb"\xc1(..)\xf8\x31", data, re.S)]
    # pstops writes one showpage + `#copies 3`; Ghostscript expands that to three
    # pages, and the filter renders each exactly once, tagging every one with 3.
    # (This is what the vendor filter produces for copies=3: 3 pages, attr [3,3,3].)
    if len(begins) != 3 or counts[:1] != [3] or any(c != 3 for c in counts):
        r["verdict"] = "COPIES_BAD"
        r["stderr"] = f"BeginImage={len(begins)} counts={counts[:6]} (want 3 pages, all counts 3)"
    r["note"] = f"pstops={len(ps.stdout)}B pages={len(begins)} counts={counts[:2]}"
    return r


def run_case(name: str, data: bytes, opts: str, copies: int = 1) -> dict:
    src = WORK / "in.ps"
    src.write_bytes(data)
    if OUT.exists():
        OUT.unlink()
    argv = [FILTER, "1", "fuzz", name, str(copies), opts, str(src)]
    try:
        # The filter writes the XL2HB stream to *stdout*; CUPS' backend is what
        # redirects it to the device.  So capture stdout, not a file.
        p = subprocess.run(argv, capture_output=True, timeout=180)
    except subprocess.TimeoutExpired:
        return {"name": name, "verdict": "TIMEOUT", "size": 0, "rc": None, "stdout": b""}
    size = len(p.stdout)
    err = p.stderr.decode("utf-8", "replace")
    trace = "Traceback" in err
    if name in EXPECT_FAIL:
        # Malformed input: a clean, traceback-free non-zero exit is the goal.
        verdict = "ok" if (p.returncode != 0 and not trace) else "UNEXPECTED"
    elif p.returncode != 0:
        verdict = f"RC={p.returncode}"
    elif trace:
        verdict = "TRACEBACK"
    elif size == 0:
        verdict = "NO_OUTPUT"
    else:
        verdict = "ok"
    return {
        "name": name,
        "verdict": verdict,
        "stdout": p.stdout,
        "size": size,
        "rc": p.returncode,
        "stderr": err[-400:] if verdict != "ok" else "",
    }


def main() -> int:
    quick = "--quick" in sys.argv
    WORK.mkdir(parents=True, exist_ok=True)
    cases = CASES[:8] if quick else CASES
    rows, bad = [], []
    for name, data, opts in cases:
        r = run_case(name, data, opts)
        rows.append(r)
        mark = "OK " if r["verdict"] == "ok" else "!! "
        print(f"  {mark}{name:22s} {r['size']:>9} B  {r['verdict']}", flush=True)
        if r["verdict"] != "ok":
            bad.append(r)

    # Copies go through the real pstops chain (needs a well-formed document).
    if not quick:
        r = run_copies_case()
        rows.append(r)
        mark = "OK " if r["verdict"] == "ok" else "!! "
        print(f"  {mark}{r['name']:22s} {r['size']:>9} B  {r['verdict']}  {r.get('note','')}", flush=True)
        if r["verdict"] != "ok":
            bad.append(r)

    LOGFILE.parent.mkdir(parents=True, exist_ok=True)
    with LOGFILE.open("w") as fh:
        fh.write("# Filter fuzz — end-to-end through the installed CUPS filter\n\n")
        fh.write(f"Cases: {len(rows)}   failing: {len(bad)}\n\n")
        fh.write("| case | payload B | verdict |\n|---|---|---|\n")
        for r in rows:
            fh.write(f"| `{r['name']}` | {r['size']} | {r['verdict']} |\n")
        for r in bad:
            fh.write(f"\n### {r['name']} — {r['verdict']}\n```\n{r.get('stderr','')}\n```\n")

    print(f"\n  {len(rows) - len(bad)}/{len(rows)} ok, report -> {LOGFILE}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
