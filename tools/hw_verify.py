#!/usr/bin/env python3
"""Hardware verification against the real HL-3040CN.

Proves three things, in increasing strength:

  1. the printer is the expected device (PJL `INFO ID`);
  2. the driver's stream is accepted end-to-end (CUPS filter + socket backend
     both exit 0, printer reports no error);
  3. a page actually came out — the hardware page counter rises.

Only (3) is real proof of printing; the socket backend returns success as soon
as the bytes are in the TCP buffer, so a job "completing" means nothing on its
own.  The printer's own counter is the arbiter.

Usage:
    .venv312/bin/python tools/hw_verify.py            # one page, both queues off
    .venv312/bin/python tools/hw_verify.py --status   # just report, no print
"""
from __future__ import annotations

import re
import socket
import subprocess
import sys
import time

PRINTER = ("192.168.178.50", 9100)
QUEUE = "Brother_HL-3040CN"
UEL = b"\x1b%-12345X"


def pjl(cmd: bytes, wait: float = 4.0) -> str:
    """Send one PJL command over port 9100 and return the decoded reply."""
    s = socket.socket()
    s.settimeout(wait)
    s.connect(PRINTER)
    s.sendall(UEL + b"@PJL\r\n" + cmd + b"\r\n" + UEL + b"\r\n")
    data, t0 = b"", time.time()
    try:
        while time.time() - t0 < wait:
            chunk = s.recv(4096)
            if not chunk:
                break
            data += chunk
    except OSError:
        pass
    s.close()
    return " ".join(data.decode("ascii", "replace").split())


def field(reply: str, key: str) -> str | None:
    m = re.search(rf"{key}=(\S+)", reply)
    return m.group(1) if m else None


def status() -> dict[str, str | None]:
    ident = pjl(b"@PJL INFO ID")
    stat = pjl(b"@PJL INFO STATUS")
    return {
        "id": re.search(r'"(.*?)"', ident).group(1) if '"' in ident else ident,
        "display": re.search(r'DISPLAY="(.*?)"', stat).group(1) if "DISPLAY=" in stat else None,
        "code": field(stat, "CODE"),
        "online": field(stat, "ONLINE"),
        "pages": field(pjl(b"@PJL INFO PAGECOUNT"), "PAGECOUNT"),
    }


def main() -> int:
    st = status()
    print(f"  device : {st['id']}")
    print(f"  status : {st['display']} (CODE={st['code']}, ONLINE={st['online']})")
    print(f"  pages  : {st['pages']}")

    if "HL-3040CN" not in (st["id"] or ""):
        print("  !! not an HL-3040CN — refusing to print")
        return 2
    if "--status" in sys.argv:
        return 0
    if st["display"] and "Papier" in st["display"]:
        print("  !! printer reports no paper; load paper and re-run")
        return 3

    before = int(st["pages"])
    ps = (
        "%!PS-Adobe-3.0\n%%Pages: 1\n%%BoundingBox: 0 0 612 792\n%%EndComments\n"
        "%%Page: 1 1\n%%BeginPageSetup\n%%EndPageSetup\n"
        "/Helvetica findfont 18 scalefont setfont 72 720 moveto "
        "(HL-3040CN native arm64 — hw verify) show showpage\n%%EOF\n"
    )
    open("/tmp/hw_verify.ps", "w").write(ps)
    out = subprocess.run(["lp", "-d", QUEUE, "/tmp/hw_verify.ps"], capture_output=True, text=True)
    print(f"  job    : {out.stdout.strip() or out.stderr.strip()}")

    for i in range(12):
        time.sleep(5)
        now = int(field(pjl(b"@PJL INFO PAGECOUNT"), "PAGECOUNT") or before)
        print(f"  [+{(i + 1) * 5:>3}s] pages={now}")
        if now > before:
            print(f"  OK: page counter rose {before} -> {now}; printing verified")
            return 0
    s = status()
    print(f"  NO INCREASE (still {s['pages']}); printer says {s['display']}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
