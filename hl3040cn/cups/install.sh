#!/bin/bash
#
# Install the open-source Brother HL-3040CN CUPS driver.
# Requires: root, Python 3 (3.9+; 3.11 and 3.12 are tested),
#           Ghostscript, CUPS.
#
# The driver needs Brother's calibration tables. Run
#   ../scripts/extract_blobs.sh
# once before installing, otherwise dithering falls back to Bayer and the
# output will not match the original.
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"

LIB_DIR="/usr/local/lib/brhl3040cn"
VENV_DIR="$LIB_DIR/.venv"
CUPS_PPD_DIR="/usr/share/cups/model"
CUPS_FILTER_DIR="/usr/lib/cups/filter"

# The printer this driver was built for.
DEFAULT_URI="socket://192.168.178.50:9100"
QUEUE_NAME="Brother_HL-3040CN"

ADD_PRINTER=false
PRINTER_URI=""

usage() {
    echo "Usage: $0 [--add-printer [URI]]"
    echo ""
    echo "Options:"
    echo "  --add-printer [URI]  Create a CUPS queue after installing."
    echo "                       Defaults to $DEFAULT_URI"
    exit 1
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --add-printer)
            ADD_PRINTER=true
            if [[ ${2:-} && ! ${2:-} == --* ]]; then
                PRINTER_URI="$2"
                shift
            fi
            shift
            ;;
        -h|--help) usage ;;
        *) echo "Unknown option: $1"; usage ;;
    esac
done

if [[ $EUID -ne 0 ]]; then
    echo "Error: This script must be run with sudo."
    exit 1
fi

echo "Checking dependencies..."

if ! command -v python3 &>/dev/null; then
    echo "Error: python3 not found."
    exit 1
fi
PY_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
echo "  Python $PY_VERSION"

if ! command -v gs &>/dev/null; then
    echo "Error: Ghostscript (gs) not found. Install it first: apt install ghostscript"
    exit 1
fi
echo "  Ghostscript: $(gs --version)"

# CUPS puts its admin tools in /usr/sbin, which is not in every PATH.
export PATH="/usr/sbin:/usr/bin:/sbin:/bin:$PATH"

if [[ ! -x /usr/sbin/cupsd ]]; then
    echo "Error: CUPS not found. Install it first: apt install cups"
    exit 1
fi
echo "  CUPS: $(cups-config --version 2>/dev/null || echo present)"

echo "Installing library files to $LIB_DIR..."
mkdir -p "$LIB_DIR"
cp "$REPO_ROOT/src/"*.py "$LIB_DIR/"

# The filter runs as user "lp", so every module must be world-readable.
# Source files that were created with a 600 umask would otherwise make
# the filter die with PermissionError before it sends anything.
chmod 644 "$LIB_DIR"/*.py
find "$LIB_DIR" -name "__pycache__" -prune -o -type f -exec chmod a+r {} +

# Colour tables the pipeline loads by name.
if compgen -G "$REPO_ROOT/src/color_data/*.bin" >/dev/null; then
    mkdir -p "$LIB_DIR/color_data"
    cp "$REPO_ROOT/src/color_data/"*.bin "$LIB_DIR/color_data/"
    echo "  Colour tables installed ($(ls "$LIB_DIR/color_data" | wc -l) files)."
fi

# BRCD dither tables. Without these the pipeline silently falls back to a
# 32x32 Bayer matrix, which prints with visible structure.
if compgen -G "$REPO_ROOT/src/lut/*.bin" >/dev/null; then
    mkdir -p "$LIB_DIR/lut"
    cp "$REPO_ROOT/src/lut/"*.bin "$LIB_DIR/lut/"
    echo "  Dither tables installed ($(ls "$LIB_DIR/lut" | wc -l) files)."
else
    echo "  WARNING: no dither tables in $REPO_ROOT/src/lut/"
    echo "           printing will fall back to Bayer dithering."
fi

echo "Creating virtual environment at $VENV_DIR..."
python3 -m venv "$VENV_DIR"
"$VENV_DIR/bin/pip" install --quiet --upgrade pip
# 1.24 is the newest numpy available for this board's Python 3.11 and
# covers every API the pipeline uses (unpackbits, packbits, memmap,
# frombuffer). The 4150 project asks for >=2.5.3, which needs 3.12+.
"$VENV_DIR/bin/pip" install --quiet "numpy>=1.24"

echo "Precomputing inverse colour LUTs (takes about two minutes on this board)..."
if ! (cd "$LIB_DIR" && PYTHONPATH="$LIB_DIR" "$VENV_DIR/bin/python3" cli.py --precompute-lut); then
    echo "  WARNING: inverse LUT precompute failed; per-pixel interpolation will be used."
fi

# The interpolation weights are a pure function of the grid geometry, so the
# cached form is byte-identical to generating them analytically. Writing it
# once avoids recomputing it on every job and silences the "generating
# analytically" line. color_data/ is gitignored (Brother's tables are not
# redistributed), so this has to happen here, not in the repository.
# Run from $LIB_DIR, like the precompute step above: the heredoc imports
# color_lut_gen and writes color_data/interp_tables.bin relative to the working
# directory, so from anywhere else the import fails and `set -e` aborts the
# install right here -- leaving the filter, PPD and Cython build uninstalled.
echo "Caching interpolation weight tables..."
(cd "$LIB_DIR" && "$VENV_DIR/bin/python3" - <<'PY'
import sys
from pathlib import Path

sys.path.insert(0, str(Path.cwd()))
from color_lut_gen import generate_interp_tables  # noqa: E402

target = Path("color_data/interp_tables.bin")
if target.exists():
    print(f"  {target} already present, keeping it.")
else:
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(generate_interp_tables().tobytes())
    print(f"  Wrote {target} ({target.stat().st_size} bytes).")
PY
)

echo "Building acceleration kernels..."
KERNELS_BUILT=0
# Prefer Rust: no C compiler and no cython.  Fall back to the Cython kernels
# when cargo is missing or the build fails -- the pure-Python path is
# byte-identical, just slower.
if [ -d "$REPO_ROOT/rust" ] && command -v cargo >/dev/null 2>&1; then
    if (cd "$REPO_ROOT/rust" && cargo build --release >/dev/null 2>&1); then
        # A stale Cython .so would shadow the shim: an extension module wins
        # over a .py of the same name.  Park them first.
        if compgen -G "$LIB_DIR/_*_fast*.so" >/dev/null; then
            STALE_DIR="$LIB_DIR/.stale-so-$(date +%Y%m%d-%H%M%S)"
            mkdir -p "$STALE_DIR"
            mv "$LIB_DIR/"_*_fast*.so "$STALE_DIR/"
        fi
        cp "$REPO_ROOT/rust/target/release/lib_hl3040cn_native.so" "$LIB_DIR/_hl3040cn_native.so"
        cp "$REPO_ROOT/rust/shims/"_*_fast.py "$LIB_DIR/" 2>/dev/null || true
        echo "  Rust kernels installed."
        KERNELS_BUILT=1
    fi
fi

if [ "$KERNELS_BUILT" -eq 0 ]; then
    echo "  cargo unavailable or build failed; building Cython kernels..."
    BUILD_DIR="$(mktemp -d)"
    mkdir -p "$BUILD_DIR/src"
    cp "$REPO_ROOT/setup_cython.py" "$BUILD_DIR/" 2>/dev/null || true
    cp "$REPO_ROOT/src/"_*_fast.pyx "$BUILD_DIR/src/" 2>/dev/null || true
    cp "$REPO_ROOT/src/"_*_fast.pxd "$BUILD_DIR/src/" 2>/dev/null || true
    # --force: setuptools skips a .pyx whose .c file is newer and never
    # notices a .pxd edit, so an incremental build can leave a stale .so.
    if "$VENV_DIR/bin/pip" install --quiet cython setuptools \
        && (cd "$BUILD_DIR" && "$VENV_DIR/bin/python3" setup_cython.py build_ext --inplace --force >/dev/null 2>&1) \
        && compgen -G "$BUILD_DIR/src/_*_fast*.so" >/dev/null; then
        cp "$BUILD_DIR/src/"_*_fast*.so "$LIB_DIR/"
        echo "  Cython extensions installed."
    else
        # A stale .so is worse than none: an old module whose signature no longer
        # matches pipeline.py aborts every job that uses it.  This happened once --
        # an 18-argument _band_fast broke Normal mode, while Fine (which never calls
        # it) kept working, so the queue looked healthy.  Quarantine whatever is
        # installed and let the pure-Python fallback run; it is byte-identical,
        # just slower.
        if compgen -G "$LIB_DIR/_*_fast*.so" >/dev/null; then
            STALE_DIR="$LIB_DIR/.stale-so-$(date +%Y%m%d-%H%M%S)"
            mkdir -p "$STALE_DIR"
            mv "$LIB_DIR/"_*_fast*.so "$STALE_DIR/"
            echo "  WARNING: Cython build failed; pure-Python fallback will be used."
            echo "           Stale extensions quarantined in $STALE_DIR."
        else
            echo "  WARNING: Cython build failed; pure-Python fallback will be used."
        fi
    fi
    rm -rf "$BUILD_DIR"
fi

echo "Installing CUPS filter to $CUPS_FILTER_DIR..."
mkdir -p "$CUPS_FILTER_DIR"
cat > "$CUPS_FILTER_DIR/brhl3040cn-filter" << WRAPPER_EOF
#!/bin/bash
# CUPS filter wrapper for the Brother HL-3040CN (open source).
LIB_DIR="$LIB_DIR"
VENV_DIR="$VENV_DIR"
export PATH="\$VENV_DIR/bin:\$PATH"
export PYTHONPATH="\$LIB_DIR"
exec "\$VENV_DIR/bin/python3" "\$LIB_DIR/brhl3040cn-filter.py" "\$@"
WRAPPER_EOF
chmod 755 "$CUPS_FILTER_DIR/brhl3040cn-filter"

cp "$SCRIPT_DIR/brhl3040cn-filter" "$LIB_DIR/brhl3040cn-filter.py"
chmod 644 "$LIB_DIR/brhl3040cn-filter.py"

# The CUPS filter user cannot write __pycache__ here, so without this every
# job recompiles every module.
"$VENV_DIR/bin/python3" -m compileall -q "$LIB_DIR"/*.py

echo "Installing PPD to $CUPS_PPD_DIR..."
mkdir -p "$CUPS_PPD_DIR"
cp "$SCRIPT_DIR/brhl3040cn.ppd" "$CUPS_PPD_DIR/brhl3040cn.ppd"
chmod 644 "$CUPS_PPD_DIR/brhl3040cn.ppd"

echo ""
echo "Installation complete."
echo ""

if $ADD_PRINTER; then
    PRINTER_URI="${PRINTER_URI:-$DEFAULT_URI}"
    echo "Creating queue '$QUEUE_NAME' -> $PRINTER_URI"
    # print-quality-default=5 (high) makes Fine the default the queue
    # advertises over IPP. The PPD's *DefaultcupsPrintQuality does NOT drive
    # this attribute (CUPS keeps it at "normal"), so driverless clients
    # (Android/Mopria, Windows, AirPrint) would otherwise pre-select Normal.
    lpadmin -p "$QUEUE_NAME" -E \
        -v "$PRINTER_URI" \
        -P "$CUPS_PPD_DIR/brhl3040cn.ppd" \
        -o print-quality-default=5 \
        -D "Brother HL-3040CN (Open Source)" \
        -L "Network Printer"
    # Clients that ask CUPS-Get-Default (Android/Mopria do) get
    # client-error-not-found without this, so answer them with the queue.
    lpadmin -d "$QUEUE_NAME"
    echo "  Queue created (and set as default)."
else
    echo "To create a queue, run:"
    echo "  sudo $0 --add-printer"
    echo "or manually:"
    echo "  sudo lpadmin -p $QUEUE_NAME -E -v $DEFAULT_URI \\"
    echo "    -P $CUPS_PPD_DIR/brhl3040cn.ppd -o print-quality-default=5 \\"
    echo "    -D 'Brother HL-3040CN (Open Source)'"
    echo "  sudo lpadmin -d $QUEUE_NAME   # so CUPS-Get-Default answers"
fi
