#!/bin/bash
#
# Build the Cython acceleration modules in place.
#
# `setup_cython.py build_ext --inplace` only recompiles a module when its
# source is newer than the generated C file, so editing a `.pyx` after a build
# with a *backdated* clock (or editing a `.pxd`, which setuptools does not
# track at all) leaves a stale `.so` in place.  That is exactly how a working
# BRGray=OFF implementation sat unused in the tree while the tests reported
# the wrong bytes.  Always pass --force.
#
# Usage: build_cython.sh [python]
#
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
PYTHON="${1:-python3}"

cd "$HERE"
"$PYTHON" setup_cython.py build_ext --inplace --force

echo "built:"
ls -1 src/_*_fast*.so
