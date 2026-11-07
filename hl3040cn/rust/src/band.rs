// SPDX-License-Identifier: GPL-3.0-or-later
//! Band renderer for Normal mode: colour lookup, ordered dither and
//! sliding-window RLE for a whole band in one call.
//!
//! Rust counterpart of `_band_fast.pyx`.  Output is byte-identical to the
//! per-line path in `pipeline._render_page`: colour through the inverse LUT
//! (or interpolated in the colour grid), 1bpp threshold dither, then
//! `encode_plane` / `encode_c_plane` / `encode_m_plane_10`.
//!
//! The kernel drops the GIL, so bands render in parallel on the render
//! threads.  `test_kernel_signature.py` pins the argument list to the call
//! site in `pipeline.py`, which is why the parameters keep their exact order.

use numpy::{PyReadonlyArray1, PyReadonlyArray2, PyReadwriteArray2};
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use pyo3::types::PyBytes;

use crate::color::interp_pixel;
use crate::rle::{encode_line, OutBuf};

/// RLE word size per plane (K, C, M, Y), as in `plane_encoders`.
const BITS: [i32; 4] = [12, 20, 10, 12];

const LUT_SIZE: usize = 256 * 256 * 256 * 4;

/// Colour-convert, dither and encode `rows` (page lines from `first_line`).
#[allow(clippy::too_many_arguments)]
#[pyfunction]
pub fn render_band<'py>(
    py: Python<'py>,
    rows: PyReadonlyArray2<'py, u8>,
    skip: PyReadonlyArray1<'py, u8>,
    width: isize,
    first_line: isize,
    sw: isize,
    lut: PyReadonlyArray1<'py, u8>,
    grid: PyReadonlyArray1<'py, i32>,
    weights: PyReadonlyArray1<'py, u8>,
    black: PyReadonlyArray1<'py, i32>,
    thr_k: PyReadonlyArray2<'py, u8>,
    thr_c: PyReadonlyArray2<'py, u8>,
    thr_m: PyReadonlyArray2<'py, u8>,
    thr_y: PyReadonlyArray2<'py, u8>,
    mut lengths: PyReadwriteArray2<'py, i32>,
) -> PyResult<Bound<'py, PyBytes>> {
    let width = width as usize;
    let first_line = first_line as i64;
    let sw = sw as usize;

    let rows_v = rows.as_array();
    let n = rows_v.shape()[0];
    let ncols = rows_v.shape()[1];

    let skip_v = skip.as_array();
    let lut_v = lut.as_array();
    let has_lut = lut_v.len() != 0;

    let npx = width.min(sw);
    let bpl = (sw + 7) / 8;

    if skip_v.len() != n {
        return Err(PyValueError::new_err("skip and lengths must have one entry per row"));
    }
    {
        let l = lengths.as_array();
        if l.shape()[0] != n || l.shape()[1] != 4 {
            return Err(PyValueError::new_err("skip and lengths must have one entry per row"));
        }
    }
    if n > 0 && ncols < npx * 3 {
        return Err(PyValueError::new_err("rows shorter than width * 3"));
    }
    if ncols > 1 && rows_v.strides()[1] != 1 {
        return Err(PyValueError::new_err("rows must be contiguous scanlines"));
    }
    if has_lut && lut_v.len() != LUT_SIZE {
        return Err(PyValueError::new_err("lut must be the flat 256*256*256*4 inverse LUT"));
    }

    let grid_v = grid.as_array();
    let weights_v = weights.as_array();
    let black_v = black.as_array();
    if !has_lut && (grid_v.len() != 4913 * 4 || weights_v.len() != 17 * 289 * 9 || black_v.len() != 4) {
        return Err(PyValueError::new_err(
            "without an inverse LUT, grid, weights and black ink are required",
        ));
    }

    let tk_v = thr_k.as_array();
    let tc_v = thr_c.as_array();
    let tm_v = thr_m.as_array();
    let ty_v = thr_y.as_array();
    let thr_ok = tk_v.shape()[0] > 0
        && tc_v.shape()[0] > 0
        && tm_v.shape()[0] > 0
        && ty_v.shape()[0] > 0
        && tk_v.shape()[1] >= npx
        && tc_v.shape()[1] >= npx
        && tm_v.shape()[1] >= npx
        && ty_v.shape()[1] >= npx;
    if !thr_ok {
        return Err(PyValueError::new_err("threshold matrix narrower than the image"));
    }
    if sw == 0 {
        return Err(PyValueError::new_err("sw must be positive"));
    }

    // The colour tables are flat and contiguous by construction; `as_slice`
    // only fails on a non-contiguous view, which would be a caller bug.
    let lut_s = lut_v.as_slice().unwrap_or(&[]);
    let grid_s = grid_v.as_slice().unwrap_or(&[]);
    let weights_s = weights_v.as_slice().unwrap_or(&[]);
    let black_s = black_v.as_slice().unwrap_or(&[]);

    let thr = [tk_v, tc_v, tm_v, ty_v];
    let mut planes = vec![0u8; 4 * bpl];
    let mut o = OutBuf::default();
    let mut lengths_v = lengths.as_array_mut();
    let mut kcmy = [0u8; 4];

    for i in 0..n {
        if skip_v[i] != 0 {
            for pid in 0..4 {
                lengths_v[[i, pid]] = 0;
            }
            continue;
        }
        let line = first_line + i as i64;
        planes.iter_mut().for_each(|b| *b = 0);

        for j in 0..npx {
            let rv = rows_v[[i, 3 * j]];
            let gv = rows_v[[i, 3 * j + 1]];
            let bv = rows_v[[i, 3 * j + 2]];

            let (kv, cv, mv, yv);
            if has_lut {
                let off = (((rv as usize) << 16) | ((gv as usize) << 8) | bv as usize) << 2;
                kv = lut_s[off];
                cv = lut_s[off + 1];
                mv = lut_s[off + 2];
                yv = lut_s[off + 3];
            } else {
                interp_pixel(grid_s, weights_s, black_s, rv, gv, bv, &mut kcmy);
                kv = kcmy[0];
                cv = kcmy[1];
                mv = kcmy[2];
                yv = kcmy[3];
            }

            let bit = 0x80u8 >> (j & 7);
            let chan = [kv, cv, mv, yv];
            for pid in 0..4 {
                let trow = (line.rem_euclid(thr[pid].shape()[0] as i64)) as usize;
                if 255u16 - u16::from(chan[pid]) > u16::from(thr[pid][[trow, j]]) {
                    planes[pid * bpl + (j >> 3)] |= bit;
                }
            }
        }

        for pid in 0..4 {
            let written = encode_line(&planes[pid * bpl..(pid + 1) * bpl], BITS[pid], &mut o);
            lengths_v[[i, pid]] = written as i32;
        }
    }

    Ok(PyBytes::new(py, &o.data))
}
