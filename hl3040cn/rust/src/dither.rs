// SPDX-License-Identifier: GPL-3.0-or-later
//! Ordered-dither kernels: the Normal-mode 1bpp threshold pass and the
//! Fine-mode 4bpp BRCD pattern gather.
//!
//! Rust counterparts of `_dither_fast.pyx`.  The argument lists are kept
//! verbatim, so `hl3040cn/src/_dither_fast.py` stays a plain re-export and the
//! Python driver needs no change.

use numpy::PyReadonlyArray1;
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use pyo3::types::PyBytes;

/// Set a dot where ink (255 - pixel) exceeds the threshold; pack MSB-first.
///
/// Returns `ceil(width / 8)` bytes.
#[pyfunction]
pub fn dither_row_1bpp<'py>(
    py: Python<'py>,
    row: PyReadonlyArray1<'py, u8>,
    thresholds: PyReadonlyArray1<'py, u8>,
    width: isize,
) -> PyResult<Bound<'py, PyBytes>> {
    let row_view = row.as_array();
    let thr_view = thresholds.as_array();
    let width = width as usize;
    if row_view.len() < width || thr_view.len() < width {
        return Err(PyValueError::new_err("row or thresholds shorter than width"));
    }
    let mut out = vec![0u8; (width + 7) / 8];
    for i in 0..width {
        if 255u16 - u16::from(row_view[i]) > u16::from(thr_view[i]) {
            out[i >> 3] |= 0x80u8 >> (i & 7);
        }
    }
    Ok(PyBytes::new(py, &out))
}

/// Dither one Fine-mode scanline through the BRCD dot patterns.
///
/// Native counterpart of `dither.dither_channel_4bpp_pattern_arr`.  For each
/// pixel the ink amount selects a pattern row and the column is taken modulo the
/// pattern width; the byte's low nibble is the level, and two levels pack into
/// one output byte (high nibble first).
///
/// Returns `width // 2` nibble-packed bytes.
#[pyfunction]
pub fn dither_row_4bpp_pattern<'py>(
    py: Python<'py>,
    row: PyReadonlyArray1<'py, u8>,
    patterns: PyReadonlyArray1<'py, u8>,
    n_ink: isize,
    pattern_row_bytes: isize,
    pattern_offset: isize,
    wb: isize,
    width: isize,
) -> PyResult<Bound<'py, PyBytes>> {
    let row_view = row.as_array();
    let pats = patterns.as_array();
    let width = width as usize;
    let n_ink = n_ink as i64;
    let prb = pattern_row_bytes as i64;
    let poff = pattern_offset as i64;
    let wb = wb as i64;

    if row_view.len() < width {
        return Err(PyValueError::new_err("row shorter than width"));
    }
    if (pats.len() as i64) < n_ink * prb {
        return Err(PyValueError::new_err(
            "patterns smaller than n_ink * pattern_row_bytes",
        ));
    }
    if width % 2 != 0 {
        return Err(PyValueError::new_err("width must be even"));
    }

    let max_ink = n_ink - 1;
    let half = width / 2;
    let mut out = vec![0u8; half];
    for i in 0..half {
        let mut ink = 255i64 - i64::from(row_view[2 * i]);
        if ink > max_ink {
            ink = max_ink;
        }
        let col = poff + (2 * i as i64) % wb;
        let level0 = pats[(ink * prb + col) as usize] & 0x0F;

        let mut ink = 255i64 - i64::from(row_view[2 * i + 1]);
        if ink > max_ink {
            ink = max_ink;
        }
        let col = poff + (2 * i as i64 + 1) % wb;
        let level1 = pats[(ink * prb + col) as usize] & 0x0F;

        out[i] = (level0 << 4) | level1;
    }
    Ok(PyBytes::new(py, &out))
}
