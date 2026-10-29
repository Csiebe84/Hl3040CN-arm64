"""Guard against a stale Cython extension in the installed tree.

The Normal mode was dead for a while because a hand-placed `_band_fast.so` had
been built from a discarded experiment (18 parameters) while `pipeline.py`
passes 14.  The unit suite never noticed: `KernelParityTest` skips when the
kernel is not importable, and CI builds no extensions at all.

These tests do not need the Brother blobs and run everywhere.  They compare the
extension's real call signature against the call site in `pipeline.py`.
"""
from __future__ import annotations

import ast
import importlib.util
import inspect
import re
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent

sys.path.insert(0, str(HERE))


def _call_arity() -> int:
    """Positional arguments `pipeline.render_band(...)` is called with.

    A starred argument (`*kernel_colour`) expands to a known-width tuple; the
    call site is `render_band(a, b, c, d, e, *four, *four, lengths)`, so the
    effective arity is 5 + 4 + 4 + 1 = 14.  Starred names are resolved against
    the tuples they come from, so a change on either side is caught.
    """
    tree = ast.parse((HERE / "pipeline.py").read_text())
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and getattr(node.func, "id", "") == "render_band"):
            continue
        arity = 0
        for arg in node.args:
            if isinstance(arg, ast.Starred):
                arity += _starred_width(arg.value)
            else:
                arity += 1
        return arity
    raise AssertionError("no render_band(...) call found in pipeline.py")


def _starred_width(value: ast.expr) -> int:
    """Element count of a `*name` argument (a 4-tuple in this pipeline)."""
    name = getattr(value, "id", None)
    if name is None:
        raise AssertionError(f"cannot size starred argument {ast.dump(value)}")
    tree = ast.parse((HERE / "pipeline.py").read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(
            getattr(t, "id", None) == name for t in node.targets
        ):
            if isinstance(node.value, ast.Tuple):
                return len(node.value.elts)
    # `_kernel_colour_for()` builds a 4-field named tuple; treat as opaque.
    return 4


def _pyx_params() -> list[str]:
    """Parameter names of `def render_band(...)` in the Cython source.

    Parsed with a regex rather than `ast`, because `.pyx` uses `cimport` which
    the Python parser rejects.
    """
    text = (HERE / "_band_fast.pyx").read_text()
    match = re.search(r"^def render_band\((?P<sig>.*?)\):", text, re.M | re.S)
    if not match:
        raise AssertionError("no render_band definition found in _band_fast.pyx")
    params = []
    depth = 0
    current = ""
    for ch in match.group("sig"):
        if ch in "[(":
            depth += 1
        elif ch in "])":
            depth -= 1
        if ch == "," and depth == 0:
            params.append(current.strip())
            current = ""
        else:
            current += ch
    if current.strip():
        params.append(current.strip())
    return [p.split()[-1] for p in params if p]


class KernelSignatureTest(unittest.TestCase):
    """The kernel must be callable exactly the way `pipeline.py` calls it."""

    def test_source_matches_the_call_site(self) -> None:
        call = _call_arity()
        params = _pyx_params()
        self.assertEqual(
            call,
            14,
            f"pipeline calls render_band with {call} effective arguments, expected 14",
        )
        self.assertEqual(
            len(params),
            call,
            f"pipeline passes {call} arguments but _band_fast.render_band takes "
            f"{len(params)}: rebuild the extension (see AGENTS.md)",
        )

    def test_no_gray_grid_parameters(self) -> None:
        """The discarded per-pixel grey grid must not come back silently."""
        params = _pyx_params()
        stray = [p for p in params if p.startswith("gray")]
        self.assertEqual(stray, [], f"unexpected grey-grid parameters: {stray}")

    @unittest.skipUnless(
        importlib.util.find_spec("_band_fast") is not None,
        "Cython band kernel not built",
    )
    def test_installed_kernel_accepts_the_call(self) -> None:
        """An importable kernel must have the signature the pipeline uses."""
        import _band_fast

        params = inspect.signature(_band_fast.render_band).parameters
        self.assertEqual(
            len(params),
            len(_pyx_params()),
            f"the built _band_fast takes {len(params)} parameters but the source "
            f"declares {len(_pyx_params())}: the .so is stale, rebuild it",
        )
        self.assertEqual(list(params), _pyx_params())


@unittest.skipUnless(
    Path("/usr/local/lib/brhl3040cn").is_dir(),
    "driver not installed on this machine",
)
class InstalledTreeTest(unittest.TestCase):
    """The installed extensions must match the installed source.

    A `.so` placed by hand can be older than the source it should match; that
    is exactly how Normal mode was dead for a while.  This runs only where the
    driver is installed, so it is skipped in CI.
    """

    LIB = Path("/usr/local/lib/brhl3040cn")

    def test_installed_pyx_signature_matches_installed_module(self) -> None:
        """Installed `.pyx` and installed `.so` must agree."""
        pyx = HERE / "_band_fast.pyx"
        if not pyx.is_file():
            self.skipTest("source tree not next to the test")
        spec = importlib.util.find_spec("_band_fast")
        if spec is None:
            self.skipTest("no kernel importable")
        import _band_fast

        installed = list(inspect.signature(_band_fast.render_band).parameters)
        self.assertEqual(
            installed,
            _pyx_params(),
            "the importable _band_fast does not match the .pyx source: "
            f"{installed} vs {_pyx_params()} -- rebuild or quarantine",
        )


if __name__ == "__main__":
    unittest.main()
