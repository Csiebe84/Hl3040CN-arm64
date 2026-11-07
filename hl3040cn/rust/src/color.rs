// SPDX-License-Identifier: GPL-3.0-or-later
//! Per-scanline RGB→KCMY colour kernels.
//!
//! Rust counterparts of `_color_fast.pyx`: a gather through the flat inverse
//! LUT, and tetrahedral interpolation through the 17x17x17 colour grid.  One
//! pass over the row instead of numpy's index build + fancy-index +
//! de-interleave, which dominate the colour stage on ARM.
//!
//! `interp_pixel` mirrors `_color_fast.pxd` and `color_lut._rgb_to_cmyk_interp_arr`.

use numpy::{PyReadonlyArray1, PyReadwriteArray1};
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;

const LUT_ENTRIES: usize = 256 * 256 * 256 * 4;
const GRID_ENTRIES: usize = 4913 * 4;
const WEIGHT_ENTRIES: usize = 17 * 289 * 9;

/// Corner offsets of the 8 cube corners, in interpolation-weight order.
const CORNERS: [i64; 8] = [0, 17, 1, 18, 289, 306, 290, 307];

/// Write K, C, M, Y (0 = full ink, 255 = none) for one RGB pixel.
///
/// `grid` holds 4913 entries of C, M, Y, K ink; `weights` the 17 tables of
/// 289 x 9 bytes; `black` the C, M, Y, K ink for pure black.
#[inline]
pub(crate) fn interp_pixel(grid: &[i32], weights: &[u8], black: &[i32], r: u8, g: u8, b: u8, kcmy: &mut [u8; 4]) {
    if r == 255 && g == 255 && b == 255 {
        kcmy.copy_from_slice(&[255, 255, 255, 255]);
        return;
    }
    if r == 0 && g == 0 && b == 0 {
        kcmy[0] = (255 - black[3]) as u8;
        kcmy[1] = (255 - black[0]) as u8;
        kcmy[2] = (255 - black[1]) as u8;
        kcmy[3] = (255 - black[2]) as u8;
        return;
    }

    let (r_hi, r_frac) = if r == 255 { (15i64, 16i64) } else { ((r >> 4) as i64, (r & 15) as i64) };
    let (g_hi, g_frac) = if g == 255 { (15i64, 16i64) } else { ((g >> 4) as i64, (g & 15) as i64) };
    let (b_hi, b_frac) = if b == 255 { (15i64, 16i64) } else { ((b >> 4) as i64, (b & 15) as i64) };

    let w_off = ((b_frac * 289 + g_frac * 17 + r_frac) * 9) as usize;
    let w = &weights[w_off..w_off + 9];
    let mut total = w[0] as i64;
    if total == 0 {
        total = 1;
    }
    let base = r_hi * 289 + g_hi * 17 + b_hi;

    let mut acc = [0i64; 4];
    for k in 0..8 {
        let corner = ((base + CORNERS[k]) * 4) as usize;
        for ch in 0..4 {
            acc[ch] += (w[k + 1] as i64) * (grid[corner + ch] as i64);
        }
    }
    let half = total >> 1;
    // Ink → pixel-brightness; the uint8 casts wrap like the numpy path.
    kcmy[0] = (255 - (acc[3] + half) / total) as u8;
    kcmy[1] = (255 - (acc[0] + half) / total) as u8;
    kcmy[2] = (255 - (acc[1] + half) / total) as u8;
    kcmy[3] = (255 - (acc[2] + half) / total) as u8;
}

/// Look up `width` RGB pixels in the flat (256*256*256*4) KCMY LUT.
///
/// Writes the four channels into the preallocated `k`, `c`, `m`, `y`.
#[pyfunction]
pub fn gather_kcmy(
    rgb: PyReadonlyArray1<u8>,
    width: isize,
    lut: PyReadonlyArray1<u8>,
    mut k: PyReadwriteArray1<u8>,
    mut c: PyReadwriteArray1<u8>,
    mut m: PyReadwriteArray1<u8>,
    mut y: PyReadwriteArray1<u8>,
) -> PyResult<()> {
    let width = width as usize;
    let rgb = rgb.as_slice()?;
    let lut = lut.as_slice()?;
    if rgb.len() < width * 3 {
        return Err(PyValueError::new_err("rgb row shorter than width * 3"));
    }
    if lut.len() != LUT_ENTRIES {
        return Err(PyValueError::new_err("lut must be the flat 256*256*256*4 inverse LUT"));
    }
    let k = k.as_slice_mut()?;
    let c = c.as_slice_mut()?;
    let m = m.as_slice_mut()?;
    let y = y.as_slice_mut()?;
    if k.len() < width || c.len() < width || m.len() < width || y.len() < width {
        return Err(PyValueError::new_err("output planes shorter than width"));
    }

    for i in 0..width {
        let off = (((rgb[3 * i] as usize) << 16) | ((rgb[3 * i + 1] as usize) << 8) | rgb[3 * i + 2] as usize) << 2;
        k[i] = lut[off];
        c[i] = lut[off + 1];
        m[i] = lut[off + 2];
        y[i] = lut[off + 3];
    }
    Ok(())
}

/// Interpolate `width` RGB pixels through a 17x17x17 colour grid.
///
/// `grid`, `weights` and `black` come from `color_lut.interp_arrays`.
/// Writes the four channels into the preallocated `k`, `c`, `m`, `y`.
#[pyfunction]
pub fn interp_kcmy(
    rgb: PyReadonlyArray1<u8>,
    width: isize,
    grid: PyReadonlyArray1<i32>,
    weights: PyReadonlyArray1<u8>,
    black: PyReadonlyArray1<i32>,
    mut k: PyReadwriteArray1<u8>,
    mut c: PyReadwriteArray1<u8>,
    mut m: PyReadwriteArray1<u8>,
    mut y: PyReadwriteArray1<u8>,
) -> PyResult<()> {
    let width = width as usize;
    let rgb = rgb.as_slice()?;
    let grid = grid.as_slice()?;
    let weights = weights.as_slice()?;
    let black = black.as_slice()?;
    if rgb.len() < width * 3 {
        return Err(PyValueError::new_err("rgb row shorter than width * 3"));
    }
    if grid.len() != GRID_ENTRIES || weights.len() != WEIGHT_ENTRIES || black.len() != 4 {
        return Err(PyValueError::new_err("grid, weights or black ink has the wrong size"));
    }
    let k = k.as_slice_mut()?;
    let c = c.as_slice_mut()?;
    let m = m.as_slice_mut()?;
    let y = y.as_slice_mut()?;
    if k.len() < width || c.len() < width || m.len() < width || y.len() < width {
        return Err(PyValueError::new_err("output planes shorter than width"));
    }

    let mut kcmy = [0u8; 4];
    for i in 0..width {
        interp_pixel(grid, weights, black, rgb[3 * i], rgb[3 * i + 1], rgb[3 * i + 2], &mut kcmy);
        k[i] = kcmy[0];
        c[i] = kcmy[1];
        m[i] = kcmy[2];
        y[i] = kcmy[3];
    }
    Ok(())
}
