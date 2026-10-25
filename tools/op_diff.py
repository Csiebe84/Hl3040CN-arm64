#!/usr/bin/env python3
"""Compare oracle and native XL2HB operator streams attribute by attribute.

Byte-level diffing only says *where* two streams differ; parsing both and
comparing decoded operators says *what* differs, which is what localises a
defect to a pipeline stage instead of a byte offset.
"""
from __future__ import annotations

import io
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))
sys.path.insert(0, str(HERE.parent / "hl3040cn" / "src"))

import pclxl  # noqa: E402
import pipeline  # noqa: E402
from ppm import read_ppm  # noqa: E402
from settings import PrintSettings  # noqa: E402

FIX = Path("/mnt/ssd/bprobe")


def native_blob(name: str) -> bytes:
    """Run the native pipeline over a PPM fixture."""
    w, h, _mx, px = read_ppm(io.BytesIO((FIX / f"{name}.ppm").read_bytes()))
    s = PrintSettings()
    s.page_size = "Letter"
    buf = io.BytesIO()
    pipeline.filter_page(w, h, px, s, buf)
    return buf.getvalue()


def main() -> int:
    """Print every operator whose attributes differ between the two streams."""
    name = sys.argv[1] if len(sys.argv) > 1 else "red"
    o = pclxl.parse((FIX / f"{name}.xl2hb").read_bytes())
    n = pclxl.parse(native_blob(name))
    print(f"fixture={name}  oracle ops={len(o)}  native ops={len(n)}")
    print()
    shown = 0
    for i in range(min(len(o), len(n))):
        a, b = o[i], n[i]
        ka = {k: v for k, v in a.attrs.items() if k != "data"}
        kb = {k: v for k, v in b.attrs.items() if k != "data"}
        da, db = len(a.data or b""), len(b.data or b"")
        if a.name != b.name or ka != kb or da != db:
            shown += 1
            print(f"[{i:2d}] {a.name}")
            if a.name != b.name:
                print(f"     name: oracle={a.name} native={b.name}")
            if ka != kb:
                for key in sorted(set(ka) | set(kb)):
                    if ka.get(key) != kb.get(key):
                        print(f"     {key}:")
                        print(f"        oracle={ka.get(key)}")
                        print(f"        native={kb.get(key)}")
            if da != db:
                print(f"     data: oracle={da}B native={db}B")
            print()
            if shown >= 12:
                print("... (gekappt)")
                break
    if len(o) != len(n):
        print(f"Operatorzahl unterschiedlich: oracle={len(o)} native={len(n)}")
    if shown == 0:
        print("alle Operatoren identisch (Attribute + Datenlaengen)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
