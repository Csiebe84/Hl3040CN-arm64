# Brother HL-3040CN — native CUPS driver

An open-source CUPS driver for the Brother HL-3040CN colour laser printer,
written in Python. It speaks the printer's own **XL2HB** raster language
directly, so it runs natively on **ARM64** (Raspberry Pi, Odroid, …) and on
any other architecture CUPS runs on.

It exists because Brother's own Linux driver is a **32-bit i386 binary**.
On an ARM board that means emulation (`qemu-i386` + `binfmt_misc`), which is
slow, fragile and pulls in a whole i386 userspace. This driver removes that
dependency: no emulator, no container, no 32-bit binaries.

The port is derived from the GPL-3.0
[brother-hl4150cdn-driver](https://github.com/cl445/brother-hl4150cdn-driver),
which speaks the same raster dialect. The two printers share the block
layout, the 12-bit RLE encoder and the band configuration; the differences
are the page geometry, the colour grids and the dither set.

## Status

Working and in daily use on an Odroid N2+ (arm64, Armbian bookworm,
Python 3.11). Correctness is established by byte-level comparison against
the manufacturer's filter:

| | |
|---|---|
| XL2HB payload | **byte-identical** to Brother's filter (79503 bytes for the test page) |
| Monochrome, K-only patterns | byte-identical |
| Page geometry | all 22 paper sizes match |
| Colour separation | works; the exact grid selection is still being refined |

The only known difference in the output stream is that Brother's filter
writes an `@PJL JOB` line that this driver omits. The printer accepts both.

## Requirements

* **CUPS** (`cupsd`) — any recent version
* **Ghostscript** (`gs`) — renders the incoming PostScript to raster
* **Python 3** with `numpy`
* Optional: a C compiler and `cython` for the accelerated hot paths
  (the driver falls back to pure Python if they are missing)

Disk use is about 130 MB after installation, most of it the precomputed
inverse colour lookup tables.

## Install

```bash
git clone https://github.com/<owner>/<repo>.git
cd <repo>
./scripts/extract_blobs.sh          # see "Calibration tables" below
sudo cups/install.sh                # installs the driver, not a queue
sudo cups/install.sh --add-printer  # ... and create the CUPS queue
```

`install.sh` copies the filter to `/usr/lib/cups/filter/`, the modules to
`/usr/local/lib/brhl3040cn/`, creates a virtual environment there, builds
the Cython extensions and precomputes the colour tables. On a slow board
that takes a few minutes.

To remove everything again:

```bash
sudo cups/uninstall.sh
```

## Calibration tables (read this)

The driver needs two sets of tables that belong to the printer:

* **colour grids** — 17×17×17 CMYK lookup tables, embedded in Brother's
  filter binary,
* **BRCD dither tables** — `cache08` set, shipped in Brother's LPR package.

**These tables are not part of this repository.** They are Brother's
property and are not redistributed here. Instead, `scripts/extract_blobs.sh`
obtains them locally, from either

* the Brother HL-3040CN LPR package (`.deb`) that you downloaded yourself:
  `./scripts/extract_blobs.sh hl3040cnlpr-*.i386.deb`, or
* an installed copy of Brother's driver on the machine, e.g. inside the
  i386 Docker container this project replaces:
  `./scripts/extract_blobs.sh --from-container brother-cups`.

This keeps Brother's tables under Brother's own licence and is the same
approach the upstream HL-4150CDN project takes. Extracting them for
interoperability is covered by EU directive 2009/24/EC, Article 6.

The script verifies the SHA-256 of Brother's filter before trusting the
blob offsets, and refuses to write anything if the binary is a different
build than the one the offsets were pinned against.

Without the tables the driver still runs, but dithering falls back to a
32×32 Bayer matrix and the output no longer matches the original.

## Driver options

The PPD exposes the same controls as Brother's own driver:

| Option | Values |
|---|---|
| `PageSize` | 22 sizes (Letter, A4, A5, DL, …) |
| `BRInputSlot` | AutoSelect, Tray1, Manual |
| `BRResolution` | 600dpi |
| `BRMonoColor` | Auto, Mono, Color |
| `BRMediaType` | Plain, Thin, Thick, Bond, Envelope, Recycled, Label, Glossy, … |
| `BRColorMatching` | Normal, Vivid, None |
| `BRGray` | ON, OFF — improve gray |
| `BREnhanceBlkPrt` | ON, OFF |
| `BRTonerSaveMode` | ON, OFF |
| `BRReverse` | ON, OFF |
| `BRImproveOutput` | ON, OFF |
| `BRSkipBlank` | ON, OFF |
| `BRBrightness`, `BRContrast` | −100 … 100 |
| `BRRed`, `BRGreen`, `BRBlue` | −100 … 100 |
| `BRSaturation` | −100 … 100 |

The HL-3040CN has no duplex unit, so there is no `Duplex` option; a
missing value is treated as simplex.

## Printing from a phone (Android / iOS)

CUPS on the host can be reached over the network, which lets phones print
without any app, using the built-in printing services:

1. In `cupsd.conf` listen on the network and allow the local subnet:
   ```
   Listen 0.0.0.0:631
   Listen [::]:631
   ```
   and inside a `<Location />` block:
   ```
   Allow @LOCAL
   ```
2. Restart CUPS. Avahi advertises the queue automatically, so the phone
   finds it as "Brother_HL-3040CN".
3. On Android: *Settings → Connected devices → Printing → Default print
   service*, then pick the printer. It is offered through the Mopria path
   (IPP with PDF/URF/PWG-Raster), which this queue accepts.

Verified end-to-end from a Pixel 7: the phone renders the job, the queue
converts it to XL2HB and the printer's page counter advances.

## How it works

```
PostScript ──gs──► PPM ──pipeline──► XL2HB bands ──socket 9100──► printer
```

* `brfilter.py` — CUPS filter entry point; parses the job options from
  argv and the PPD.
* `page_stream.py`, `pipeline.py` — page rendering and band assembly.
* `color_lut.py`, `color_lut_gen.py` — colour separation and the
  inverse-LUT precompute.
* `dither.py` — BRCD and Bayer dithering.
* `fine_encoder.py`, `rle.py`, `plane_encoders.py` — the 12-bit RLE and
  plane packing that make up the XL2HB payload.
* `xl2hb.py`, `brother_encode.py` — protocol framing and the PJL wrapper.

## Development

Tests live next to the code and run without a printer:

```bash
cd hl3040cn/src
python3 -m unittest test_consistency test_gray_replace test_toner_save test_a4_geometry
```

`test_a4_geometry` needs Ghostscript. CI runs the same set
(`.github/workflows/tests.yml`).

The `tools/` directory holds the analysis helpers used to derive the
protocol: blob locators, grid solvers and the comparison harness
(`compare.py`) that diffs this driver's output against Brother's filter.

## Licence

GPL-3.0-or-later. See `LICENSE`.

The PPD is based on Brother's HL-4150CDN PPD (Copyright (C) 2005 Brother
Industries, Ltd., GPL-2.0-or-later); the modifications are GPL-3.0-or-later.

Brother's calibration tables and filter binaries are **not** distributed
here and remain the property of Brother Industries, Ltd.
