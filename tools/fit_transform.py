#!/usr/bin/env python3
"""Fit candidate colour transformations against the bit-exact oracle edges.

Ground truth: the R/G/B/gray node ramps measured error 0.  The task says the
missing stage sits between the colour LUT and dithering, so the primary
hypothesis is an ink-space map  oracle_cmyk = f(port_cmyk).

Models tried, each with a residual so a rejection is quantitative:
  H1  affine ink map      oracle = A @ port + b        (A is 4x4)
  H2  linear ink map      oracle = A @ port            (black/white preserved)
  H3  per-channel curve   oracle_ch = f(port_ch)       (already refuted, shown)
  H4  RGB matrix + LUT    oracle = port(A @ rgb)       (hue/saturation before)

Missing oracle planes are zero ink (a plane with no ink is not emitted).

Usage: fit_transform.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "hl3040cn" / "src"))

import color_lut  # noqa: E402
from color_lut import ColorTable  # noqa: E402

PLANES = ("K", "C", "M", "Y")
NODE_VALUES = [i * 16 for i in range(16)] + [255]

# Oracle ink per node 0..16, measured bit-exactly (tools/ramp_measure.py --nodes).
ORACLE: dict[str, dict[str, list[int]]] = {
    "R": {
        "K": [255, 221, 187, 156, 125, 97, 78, 61, 46, 34, 24, 16, 9, 5, 2, 0, 0],
        "M": [0, 103, 131, 154, 173, 190, 203, 213, 223, 233, 233, 233, 231, 228, 223, 219, 213],
        "Y": [0, 83, 105, 127, 150, 171, 181, 192, 202, 213, 214, 216, 217, 211, 205, 198, 190],
    },
    "G": {
        "K": [255, 238, 209, 182, 156, 131, 105, 88, 69, 55, 40, 28, 20, 12, 6, 2, 0],
        "Y": [0, 137, 153, 168, 184, 199, 215, 225, 235, 242, 238, 235, 232, 228, 225, 222, 218],
    },
    "B": {
        "K": [255, 222, 172, 126, 92, 65, 46, 31, 20, 12, 7, 4, 2, 1, 0, 0, 0],
        "M": [0, 42, 68, 95, 105, 115, 117, 119, 117, 114, 112, 109, 107, 104, 101, 99, 96],
    },
}
COORD = {"R": 0, "G": 1, "B": 2}


def port_ink(table: ColorTable, rgb: tuple[int, int, int]) -> np.ndarray:
    """Port's ink vector [K, C, M, Y] for one colour."""
    k, c, m, y = color_lut.rgb_to_cmyk_lut_arr(bytes(rgb) * 1, 1, table)
    return np.array([255 - int(k[0]), 255 - int(c[0]), 255 - int(m[0]), 255 - int(y[0])], dtype=np.float64)


def gather(table: ColorTable) -> tuple[np.ndarray, np.ndarray, list[str]]:
    """Build the (port_ink, oracle_ink) design matrices over the R/G/B edges."""
    x, y, labels = [], [], []
    for axis, planes in ORACLE.items():
        for node, val in enumerate(NODE_VALUES):
            rgb = [0, 0, 0]
            rgb[COORD[axis]] = val
            p = port_ink(table, tuple(rgb))
            o = np.array([planes.get(pl, [0] * 17)[node] for pl in PLANES], dtype=np.float64)
            x.append(p)
            y.append(o)
            labels.append(f"{axis}{node}")
    return np.array(x), np.array(y), labels


def fit_affine(x: np.ndarray, y: np.ndarray) -> tuple[np.ndarray, np.ndarray, float]:
    """Least-squares oracle = A @ port + b; returns (A, b, max|residual|)."""
    n = x.shape[0]
    design = np.hstack([x, np.ones((n, 1))])
    coef, *_ = np.linalg.lstsq(design, y, rcond=None)  # (5, 4)
    a = coef[:4].T
    b = coef[4]
    pred = design @ coef
    return a, b, float(np.abs(pred - y).max())


def fit_linear(x: np.ndarray, y: np.ndarray) -> tuple[np.ndarray, float]:
    """Least-squares oracle = A @ port (no offset); returns (A, max|residual|)."""
    a, *_ = np.linalg.lstsq(x, y, rcond=None)
    return a.T, float(np.abs(x @ a - y).max())


def main() -> int:
    """Fit and report each model's residual."""
    table = ColorTable("rgb")
    x, y, labels = gather(table)
    print(f"table={table.name}  samples={len(x)}  (R/G/B node edges, planes K,C,M,Y)")

    a_aff, b_aff, r_aff = fit_affine(x, y)
    print(f"H1 affine ink map   max|res|={r_aff:8.2f}")
    print("   A (rows=oracle K,C,M,Y; cols=port K,C,M,Y):")
    for row in a_aff:
        print("     " + " ".join(f"{v:8.4f}" for v in row))
    print("   b = " + " ".join(f"{v:8.4f}" for v in b_aff))

    a_lin, r_lin = fit_linear(x, y)
    print(f"H2 linear ink map   max|res|={r_lin:8.2f}")
    for row in a_lin:
        print("     " + " ".join(f"{v:8.4f}" for v in row))

    # H3 per-channel curve: for each plane, is oracle a function of port?
    print("H3 per-channel curve (monotone function test):")
    for j, pl in enumerate(PLANES):
        pairs = sorted(zip(x[:, j], y[:, j]))
        viol = sum(1 for i in range(1, len(pairs)) if pairs[i][1] < pairs[i - 1][1] - 0.5)
        span = max(p[1] for p in pairs) - min(p[1] for p in pairs)
        print(f"   {pl}: pairs={len(pairs)} monotonicity violations={viol} oracle-span={span:.0f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
