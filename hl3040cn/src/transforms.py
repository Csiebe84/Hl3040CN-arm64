"""Per-pixel and per-row colour transforms applied before the 3D-LUT lookup.

* :func:`build_input_remap_lut` / :func:`apply_input_remap_rgb` apply
  brightness, contrast, and per-channel RGB-key shifts as a single 256-entry
  per-channel input remap.
* :func:`color_table` picks the colour grid the original driver would use
  for the settings; :func:`color_lut.rgb_to_cmyk_lut_arr` separates RGB
  into CMYK through it. Colour matching and BRGray only choose the grid;
  they do not touch the pixels.
"""

import _compat  # noqa: F401  (Buffer on Python < 3.12)
from collections.abc import Buffer

import numpy as np
import numpy.typing as npt

from color_lut import ColorTable, Profile
from settings import ColorMatching, PrintSettings, Resolution

_NDArrayU8 = npt.NDArray[np.uint8]

_PROFILES: dict[ColorMatching, Profile] = {
    ColorMatching.NORMAL: "rgb",
    ColorMatching.VIVID: "srgb",
    ColorMatching.NONE: "cmyk",
}


def color_table(settings: PrintSettings) -> ColorTable:
    """The colour grid `lookup_color_transform_table` selects for `settings`.

    Measured against the oracle: colour matching and BRGray are both whole-page
    grid selectors, independent of the pixel data. Normal uses the rgb grids,
    Vivid the srgb grids, and None the cmyk grids; BRGray=ON picks the
    ImpGray=ON grid (`improve_gray=True`), BRGray=OFF the ImpGray=OFF grid.
    Every pixel, grey or not, goes through the selected grid. Rich black
    (BREnhanceBlkPrt) takes grid entry 0 for pure black in the rgb/srgb
    profiles.

    Returns:
        The table for the colour separation.
    """
    profile = _PROFILES[settings.color_matching]
    # Rich black applies only to the rgb/srgb profiles (BREnhanceBlkPrt,
    # `lut_selection` 0); colour matching None is left on the plain grid.
    rich_black = settings.enhance_black and profile != "cmyk"
    # BRResolution=Fine selects the CAPT (2400 dpi class) separation grid.
    # The filter ships a distinct grid per profile/ImpGray for it; reusing the
    # 600 dpi grid leaves a black component on mid greys the oracle drops.
    capt = settings.resolution == Resolution.FINE and profile != "cmyk"
    return ColorTable(
        profile=profile,
        improve_gray=settings.improve_gray,
        rich_black=rich_black,
        capt=capt,
    )


def build_input_remap_lut(brightness: int, contrast: int, channel: int) -> npt.NDArray[np.uint8]:
    """Build a 256-entry RGB-input remap LUT for one channel.

    Per source value ``v``, applied left-to-right with clamp to [0,255]
    after each step:

        val = v + trunc(brightness * 255 / 128)
        val = val + trunc((val - 128) * contrast / 100)
        val = val + trunc(channel * 255 / 128)

    Truncation is toward zero.

    Returns:
        256-entry uint8 LUT mapping source value to remapped value.
    """
    bright_shift = int(brightness * 255 / 128)
    chan_shift = int(channel * 255 / 128)
    v = np.arange(256, dtype=np.int32)
    val = np.clip(v + bright_shift, 0, 255)
    contrast_delta = (val - 128) * contrast
    sign = np.sign(contrast_delta)
    contrast_delta = sign * (np.abs(contrast_delta) // 100)
    val = np.clip(val + contrast_delta, 0, 255)
    val = np.clip(val + chan_shift, 0, 255)
    return val.astype(np.uint8)


def apply_input_remap_rgb(
    rgb_row: Buffer,
    width: int,
    lut_r: npt.NDArray[np.uint8],
    lut_g: npt.NDArray[np.uint8],
    lut_b: npt.NDArray[np.uint8],
) -> bytes:
    """Apply per-channel input-remap LUT to an RGB scanline.

    Pure-white pixels (255,255,255) are passed through untouched so negative
    brightness/contrast does not deposit ink on the page background.

    Returns:
        Remapped RGB bytes (same length as input).
    """
    rgb = np.frombuffer(rgb_row, dtype=np.uint8, count=width * 3).reshape(width, 3)
    out = np.empty_like(rgb)
    out[:, 0] = lut_r[rgb[:, 0]]
    out[:, 1] = lut_g[rgb[:, 1]]
    out[:, 2] = lut_b[rgb[:, 2]]
    is_white = (rgb[:, 0] == 255) & (rgb[:, 1] == 255) & (rgb[:, 2] == 255)
    out[is_white] = rgb[is_white]
    return out.tobytes()
