"""Compatibility shim for Python versions that predate `collections.abc.Buffer`.

`Buffer` was added to `collections.abc` in Python 3.12.  The driver only uses
it as a type annotation for things that support the buffer protocol, so on
older interpreters it is enough to bind it to a type that those objects do
match.  Importing this module first makes `from collections.abc import Buffer`
work everywhere the driver runs.
"""

from __future__ import annotations

import collections.abc as _abc

if not hasattr(_abc, "Buffer"):

    class Buffer:
        """Stand-in for `collections.abc.Buffer` on Python < 3.12."""

    _abc.Buffer = Buffer  # type: ignore[attr-defined]
