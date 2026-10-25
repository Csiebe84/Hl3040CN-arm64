#!/bin/bash
#
# Uninstall the open-source Brother HL-3040CN CUPS driver.
#
set -euo pipefail

# CUPS puts its admin tools in /usr/sbin, which is not in every PATH.
export PATH="/usr/sbin:/usr/bin:/sbin:/bin:$PATH"

LIB_DIR="/usr/local/lib/brhl3040cn"
CUPS_PPD_DIR="/usr/share/cups/model"
CUPS_FILTER_DIR="/usr/lib/cups/filter"
QUEUE_NAME="Brother_HL-3040CN"

REMOVE_PRINTER=false

usage() {
    echo "Usage: $0 [--remove-printer]"
    echo ""
    echo "Options:"
    echo "  --remove-printer  Also delete the CUPS queue."
    echo ""
    echo "Must be run with sudo."
    exit 1
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --remove-printer) REMOVE_PRINTER=true; shift ;;
        -h|--help) usage ;;
        *) echo "Unknown option: $1"; usage ;;
    esac
done

if [[ $EUID -ne 0 ]]; then
    echo "Error: This script must be run with sudo."
    exit 1
fi

echo "Uninstalling Brother HL-3040CN open-source driver..."

if $REMOVE_PRINTER; then
    if lpstat -p "$QUEUE_NAME" &>/dev/null; then
        echo "  Removing queue '$QUEUE_NAME'..."
        # Cancel pending jobs first; a queue with jobs refuses deletion.
        cancel -a "$QUEUE_NAME" 2>/dev/null || true
        lpadmin -x "$QUEUE_NAME"
        echo "  Queue removed."
    else
        echo "  Queue '$QUEUE_NAME' not found, nothing to remove."
    fi
else
    if lpstat -p "$QUEUE_NAME" &>/dev/null; then
        echo "  Note: queue '$QUEUE_NAME' still exists."
        echo "        Remove it with: $0 --remove-printer"
    fi
fi

echo "  Removing filter..."
rm -f "$CUPS_FILTER_DIR/brhl3040cn-filter"

echo "  Removing PPD..."
rm -f "$CUPS_PPD_DIR/brhl3040cn.ppd"

echo "  Removing library ($LIB_DIR)..."
rm -rf "$LIB_DIR"

echo ""
echo "Uninstall complete."
