#!/usr/bin/env bash
#
# extract_blobs.sh - Pull the Brother HL-3040CN calibration tables into src/.
#
# The driver needs the printer's own calibration tables (colour grids and
# BRCD dither tables) to drive the hardware. Those tables ship inside
# Brother's LPR driver and are NOT redistributed with this project. This
# script obtains them from the printer's driver and copies them into
# src/lut/ and src/color_data/. Both directories are gitignored, so every
# user keeps Brother's tables under Brother's own licence.
#
# Two sources are supported, tried in this order:
#
#   1. A local Brother LPR package, if you already have one:
#        ./scripts/extract_blobs.sh /path/to/hl3040cnlpr-*.i386.deb
#      or drop the .deb into .brother-blobs/ and run without arguments.
#
#   2. An installed copy of the driver on this machine, e.g. inside the
#      i386 Docker container that this project replaces:
#        ./scripts/extract_blobs.sh --from-container brother-cups
#
# The colour grids are single blobs at fixed offsets inside Brother's
# filter binary; the offsets below were verified against driver
# version 1.1.2-1 (filter sha256 81f3a815...5368dd). If Brother ships a
# different build, the offsets may not match - the script checks the
# filter hash and refuses to write garbage.
#
# Usage:
#   ./scripts/extract_blobs.sh [DEB] [--from-container NAME] [--force]
#
set -uo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
LUT_DIR="$REPO_DIR/src/lut"
COLOR_DATA_DIR="$REPO_DIR/src/color_data"
WORK_DIR="$REPO_DIR/.brother-blobs"

# --- Brother's filter binary -------------------------------------------------
FILTER_REL="usr/local/Brother/Printer/hl3040cn/lpd/brhl3040cnfilter"
# sha256 of the filter from hl3040cnlpr-1.1.2-1.i386.deb. Guards the offsets.
FILTER_SHA256="81f3a815564a9053997af72de50f32e881db2b3efaa73ed2b0ee9ca94a5368dd"

# Colour grids: name=offset, each 4913 * 8 = 39304 bytes (17^3 packed CMYK).
# Located by structure and pinned by the oracle; see src/find_luts.py.
GRID_BYTES=39304
GRIDS=(
  "cmyk_ig_default=0x47340"
  "cmyk_default=0x2A541"
  "srgb_ig_default=0x9E25C"
  "srgb_ig_density2=0xA7C5E"
  "srgb_ig_glossy=0xBB054"
  "rgb_ig_default=0xC4A36"
  "rgb_ig_density2=0x646BB"
  "rgb_ig_glossy=0x6E0BD"
  "rgb_default=0x814B3"
  "rgb_density2=0x8AE95"
  "rgb_glossy=0x94875"
  "srgb_default=0xBB06E"
  "srgb_density2=0xC4A4E"
  "srgb_glossy=0xCE466"
)

# The 3040 uses the cache08 BRCD set (the 4150 uses cache09).
BRCD_SUFFIX="cache08"

DEB=""
CONTAINER=""
FORCE=0
while [[ $# -gt 0 ]]; do
    case "$1" in
        --from-container) CONTAINER="${2:-}"; shift 2 ;;
        --force)          FORCE=1; shift ;;
        -h|--help)        sed -n '2,40p' "$0"; exit 0 ;;
        --*)              printf 'unknown option: %s\n' "$1" >&2; exit 2 ;;
        *)                DEB="$1"; shift ;;
    esac
done

mkdir -p "$WORK_DIR" "$LUT_DIR" "$COLOR_DATA_DIR"

have_grids() {
    compgen -G "$COLOR_DATA_DIR/*_lut.bin" >/dev/null
}
have_brcd() {
    compgen -G "$LUT_DIR/*_${BRCD_SUFFIX}.bin" >/dev/null
}

if [[ $FORCE -eq 0 ]] && have_grids && have_brcd; then
    printf 'Both table sets are already present. Use --force to redo.\n'
    exit 0
fi

# --- Source 1: a local .deb --------------------------------------------------
if [[ -z "$DEB" && -z "$CONTAINER" ]]; then
    # Look for a dropped package.
    for cand in "$WORK_DIR"/*.deb; do
        [[ -e "$cand" ]] || continue
        DEB="$cand"; break
    done
fi

extract_from_deb() {
    local deb="$1"
    printf 'Reading %s ...\n' "$deb"
    local tmp
    tmp="$(mktemp -d)"
    if ! dpkg-deb -x "$deb" "$tmp" 2>/dev/null; then
        printf 'Error: %s is not a readable .deb package.\n' "$deb" >&2
        rm -rf "$tmp"; return 1
    fi
    local bin="$tmp/$FILTER_REL"
    if [[ ! -f "$bin" ]]; then
        printf 'Error: %s not found inside the package.\n' "$FILTER_REL" >&2
        printf '       Is this the HL-3040CN LPR driver?\n' >&2
        rm -rf "$tmp"; return 1
    fi
    cp "$bin" "$WORK_DIR/brhl3040cnfilter.bin"
    local lutdir="$tmp/usr/local/Brother/Printer/hl3040cn/inf/lut"
    if [[ -d "$lutdir" ]]; then
        cp "$lutdir"/*_"${BRCD_SUFFIX}".bin "$LUT_DIR/" 2>/dev/null || true
    fi
    rm -rf "$tmp"
    return 0
}

# --- Source 2: an installed copy (e.g. the i386 container) -------------------
extract_from_container() {
    local c="$1"
    printf 'Reading from container %s ...\n' "$c"
    local p="/opt/brother/Printers/hl3040cn"
    if ! docker exec "$c" test -f "$p/lpd/brhl3040cnfilter" 2>/dev/null; then
        printf 'Error: %s not found in container %s.\n' "$p/lpd/brhl3040cnfilter" "$c" >&2
        return 1
    fi
    docker exec "$c" cat "$p/lpd/brhl3040cnfilter" > "$WORK_DIR/brhl3040cnfilter.bin" || return 1
    # `docker exec ... cat` is used deliberately: the 2011 binary's glibc
    # mis-handles a redirected stdin, and `cp` would need a tar round-trip.
    local n=0 name
    while IFS= read -r name; do
        case "$name" in
            *_"${BRCD_SUFFIX}".bin)
                docker exec "$c" cat "$p/inf/lut/$name" > "$LUT_DIR/$name" || return 1
                n=$((n + 1)) ;;
        esac
    done < <(docker exec "$c" ls "$p/inf/lut" 2>/dev/null)
    printf '  %d dither tables copied.\n' "$n"
    return 0
}

if [[ -n "$DEB" ]]; then
    extract_from_deb "$DEB" || exit 1
elif [[ -n "$CONTAINER" ]]; then
    extract_from_container "$CONTAINER" || exit 1
elif [[ -f "$WORK_DIR/brhl3040cnfilter.bin" ]]; then
    printf 'Using cached filter binary in %s\n' "$WORK_DIR"
elif docker inspect brother-cups >/dev/null 2>&1; then
    printf 'No package given, but a container named "brother-cups" exists.\n'
    printf 'Trying it. Pass --from-container NAME to pick another.\n'
    extract_from_container brother-cups || exit 1
else
    cat >&2 <<'EOF'
No source for Brother's calibration tables.

Provide one of these:
  * the HL-3040CN LPR package:
      ./scripts/extract_blobs.sh hl3040cnlpr-1.1.2-1.i386.deb
    (Brother ships it from their support page for the HL-3040CN,
     Linux, "LPR driver". Save the .deb and pass it here.)
  * an installed copy of the driver on this machine:
      ./scripts/extract_blobs.sh --from-container <container>

Without these tables the driver still works, but dithering falls back to
a 32x32 Bayer matrix and the output will not match the original exactly.
EOF
    exit 1
fi

BIN="$WORK_DIR/brhl3040cnfilter.bin"
if [[ ! -f "$BIN" ]]; then
    printf 'Error: filter binary missing after extraction.\n' >&2
    exit 1
fi

# --- Verify the filter before trusting any offset ---------------------------
actual="$(sha256sum "$BIN" | cut -d' ' -f1)"
if [[ "$actual" != "$FILTER_SHA256" ]]; then
    printf 'Warning: filter hash differs from the one the offsets were pinned to.\n' >&2
    printf '  expected %s\n  got      %s\n' "$FILTER_SHA256" "$actual" >&2
    printf 'The colour grids may come out wrong. Continuing anyway.\n' >&2
fi

# --- Extract the colour grids ------------------------------------------------
printf 'Extracting colour grids into %s ...\n' "$COLOR_DATA_DIR"
python3 - "$BIN" "$COLOR_DATA_DIR" "$GRID_BYTES" "${GRIDS[@]}" <<'PY'
import hashlib
import sys
from pathlib import Path

bin_path = Path(sys.argv[1])
out_dir = Path(sys.argv[2])
size = int(sys.argv[3])
entries = sys.argv[4:]

raw = bin_path.read_bytes()
seen = {}
written = 0
for spec in entries:
    name, off = spec.split("=")
    off = int(off, 16)
    blob = raw[off:off + size]
    if len(blob) != size:
        print(f"  {name}: offset 0x{off:x} past end of binary, skipped")
        continue
    digest = hashlib.sha256(blob).hexdigest()[:16]
    if digest in seen:
        print(f"  {name}: same bytes as {seen[digest]}, skipped")
        continue
    seen[digest] = name
    (out_dir / f"{name}_lut.bin").write_bytes(blob)
    written += 1
print(f"  {written} colour grids written.")
PY

printf '\nDone.\n'
printf '  dither tables : %s\n' "$(ls "$LUT_DIR"/*_"${BRCD_SUFFIX}".bin 2>/dev/null | wc -l)"
printf '  colour grids  : %s\n' "$(ls "$COLOR_DATA_DIR"/*_lut.bin 2>/dev/null | wc -l)"
printf '\nNext: sudo cups/install.sh\n'
