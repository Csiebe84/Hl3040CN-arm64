#!/usr/bin/env python3
"""Build the `marker-*` attributes CUPS publishes for this printer.

CUPS fills these itself, in ``backend/snmp-supplies.c``, from the Printer MIB
(RFC 3805). Two things go wrong there for the HL-3040CN:

1. **The toners read ``-1``.** The printer leaves
   ``prtMarkerSuppliesMaxCapacity`` at 0 for all four toner cartridges, so CUPS'
   rule ``if (max_capacity > 0 && level >= 0)`` falls through and it publishes
   ``-1`` ("unknown") for every one of them. The real figures are only in
   Brother's private MIB -- see `brsupply`.

2. **Magenta and yellow come out swapped.** CUPS takes each marker's colour from
   ``prtMarkerColorantValue``, indexed by the supply's colorant index. This
   printer numbers its colorants ``1=black, 2=cyan, 3=yellow, 4=magenta`` but
   names its supplies ``…, Magenta Toner, Yellow Toner``. Supply 3 therefore
   gets colour 3, which the printer calls yellow, and the two swap.

The colour is derived from the supply's *name* here instead. The name is the
human-facing label and cannot disagree with itself, whereas the colorant table
and the supply table do.

The driver emits these as ``ATTR:`` lines on stderr. ``scheduler/statbuf.c``
recognises the prefix and ``scheduler/job.c`` stores each one on the printer, so
this is the documented way for a filter to report supplies -- no extra daemon and
no direct write into CUPS' state.
"""

from __future__ import annotations

import logging
import sys
import time
from dataclasses import dataclass

from brsupply import OID_COUNTERS, OID_MAINTENANCE, Supply, as_bytes, decode_supplies
from snmp import SnmpClient, SnmpError

logger = logging.getLogger(__name__)

# Standard Printer MIB columns, RFC 3805.
OID_SUPPLIES_DESCRIPTION = "1.3.6.1.2.1.43.11.1.1.6"
OID_SUPPLIES_TYPE = "1.3.6.1.2.1.43.11.1.1.5"
OID_SUPPLIES_LEVEL = "1.3.6.1.2.1.43.11.1.1.9"
OID_SUPPLIES_MAX_CAPACITY = "1.3.6.1.2.1.43.11.1.1.8"

# `prtMarkerSuppliesType` values, as spelled by the IPP marker-types attribute.
# CUPS numbers these from CUPS_TC_other = 1; the names are its own table.
SUPPLY_TYPES: dict[int, str] = {
    1: "other",
    2: "unknown",
    3: "toner",
    4: "waste-toner",
    5: "ink",
    6: "ink-cartridge",
    7: "ink-ribbon",
    8: "waste-ink",
    9: "opc",
    10: "developer",
    11: "fuser-oil",
    12: "solid-wax",
    13: "ribbon-wax",
    14: "waste-wax",
    15: "fuser",
    16: "corona-wire",
    17: "fuser-oil-wick",
    18: "cleaner-unit",
    19: "fuser-cleaning-pad",
    20: "transfer-unit",
    21: "toner-cartridge",
    22: "fuser-oiler",
}

# Colour keyword -> IPP hex value. This is CUPS' own table from
# `snmp-supplies.c`, limited to the colours these supply names use.
COLOR_BY_KEYWORD: dict[str, str] = {
    "black": "#000000",
    "cyan": "#00FFFF",
    "magenta": "#FF00FF",
    "yellow": "#FFFF00",
}

# Supplies whose level is a percentage rather than a count.
_PERCENT_TYPES = frozenset({"toner", "toner-cartridge", "waste-toner", "opc"})


@dataclass(frozen=True)
class Marker:
    """One entry of the marker-* attributes."""

    name: str
    type: str
    color: str
    level: int


def color_for(name: str) -> str:
    """Derive a marker colour from a supply name.

    Returns:
        An ``#RRGGBB`` value, or ``"none"`` when the name carries no colour
        (a waste box or a belt unit).
    """
    lowered = name.lower()
    for keyword, value in COLOR_BY_KEYWORD.items():
        if keyword in lowered:
            return value
    return "none"


def toner_key(name: str) -> Supply | None:
    """Map a toner supply name to its `Supply` member, or None."""
    lowered = name.lower()
    if "toner" not in lowered:
        return None
    for keyword, supply in (
        ("black", Supply.BLACK_TONER),
        ("cyan", Supply.CYAN_TONER),
        ("magenta", Supply.MAGENTA_TONER),
        ("yellow", Supply.YELLOW_TONER),
    ):
        if keyword in lowered:
            return supply
    return None


def _percent(level: int, max_capacity: int, supply_type: str) -> int:
    """Turn a raw MIB level into a percentage, or -1 when it is not known.

    Mirrors CUPS' arithmetic so the values that already work keep working: a
    percentage-type supply with a sane level and capacity is scaled, a
    receptacle is inverted (a nearly full waste box is nearly *full*, not nearly
    empty), and anything else stays unknown.
    """
    if max_capacity > 0 and level >= 0:
        value = 100 * level // max_capacity
    elif level >= 0 and level <= 100 and supply_type in _PERCENT_TYPES:
        value = level
    else:
        return -1
    return max(0, min(100, value))


def read_markers(client: SnmpClient) -> list[Marker]:
    """Read the printer's supplies and build the marker list.

    The names, types and non-toner levels come from the standard Printer MIB.
    The toner levels come from Brother's private MIB, because the standard one
    reports no capacity for them.

    Raises:
        SnmpError: If the standard MIB cannot be read.
    """
    descriptions = dict(client.walk(OID_SUPPLIES_DESCRIPTION))
    types = dict(client.walk(OID_SUPPLIES_TYPE))
    levels = dict(client.walk(OID_SUPPLIES_LEVEL))
    capacities = dict(client.walk(OID_SUPPLIES_MAX_CAPACITY))

    # The toners are the whole reason this module exists; if that read fails we
    # still report the colours, names and types, which are the other half.
    toner_percent: dict[Supply, int] = {}
    try:
        maintenance = client.get_one(OID_MAINTENANCE)
        counters = client.get_one(OID_COUNTERS)
        supplies = decode_supplies(as_bytes(maintenance), as_bytes(counters))
        toner_percent = supplies.percent
        if supplies.legacy:
            logger.info("printer uses the legacy 10-character sensor words")
    except SnmpError as exc:
        logger.warning("Brother private MIB not readable, toner levels stay unknown: %s", exc)

    markers: list[Marker] = []
    for oid, raw_name in sorted(descriptions.items(), key=lambda item: _index(item[0])):
        name = _text(raw_name)
        if not name:
            continue
        index = _index(oid)
        supply_type = SUPPLY_TYPES.get(int(types.get(_sibling(oid, OID_SUPPLIES_TYPE), 2)), "unknown")
        level = int(levels.get(_sibling(oid, OID_SUPPLIES_LEVEL), -1))
        capacity = int(capacities.get(_sibling(oid, OID_SUPPLIES_MAX_CAPACITY), 0))

        if (key := toner_key(name)) is not None and key in toner_percent:
            # The private MIB is authoritative for the toners.
            value = toner_percent[key]
        else:
            value = _percent(level, capacity, supply_type)

        markers.append(Marker(name=name, type=supply_type, color=color_for(name), level=value))

    return markers


def _index(oid: str) -> int:
    """Return the trailing table index of a column OID."""
    try:
        return int(oid.rsplit(".", 1)[1])
    except (IndexError, ValueError):
        return 0


def _sibling(oid: str, column: str) -> str:
    """Rewrite a column OID to the same table index under another column."""
    return f"{column}.{_index(oid)}"


def _text(value: object) -> str:
    """Decode a MIB description into a display string."""
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace").strip()
    if isinstance(value, str):
        return value.strip()
    return ""


def quote_name(name: str) -> str:
    """Quote a marker name the way CUPS' own backend does.

    `snmp-supplies.c` wraps each entry in ``'"…"'`` and escapes backslashes and
    quotes, because a name may itself contain a comma or a quote.
    """
    escaped = name.replace("\\", "\\\\").replace('"', '\\"').replace("'", "\\'")
    return f"'\"{escaped}\"'"


def format_lines(markers: list[Marker]) -> list[str]:
    """Render the marker list as the four ATTR lines CUPS understands.

    Returns:
        The lines, each ready to be written to stderr. Empty when there is
        nothing to report.
    """
    if not markers:
        return []
    return [
        "ATTR: marker-colors=" + ",".join(marker.color for marker in markers),
        "ATTR: marker-names=" + ",".join(quote_name(marker.name) for marker in markers),
        "ATTR: marker-types=" + ",".join(marker.type for marker in markers),
        "ATTR: marker-levels=" + ",".join(str(marker.level) for marker in markers),
    ]


def host_from_device_uri(uri: str) -> str | None:
    """Extract the printer host from a CUPS device URI.

    Returns:
        The host, or None when the URI does not name a network printer.
    """
    for scheme in ("socket://", "lpd://", "ipp://", "ipps://", "http://", "https://"):
        if not uri.startswith(scheme):
            continue
        rest = uri[len(scheme):]
        # Strip any credentials, path, port and IPv6 brackets.
        rest = rest.split("@")[-1].split("/")[0]
        if rest.startswith("["):
            return rest[1:].split("]")[0] or None
        return rest.split(":")[0] or None
    return None


def marker_lines(
    host: str,
    community: str = "public",
    timeout: float = 1.0,
    budget: float = 5.0,
) -> list[str]:
    """Read *host* and return the ATTR lines, or an empty list on any failure.

    Args:
        host: The printer's address.
        community: The SNMP community.
        timeout: Per-request timeout in seconds.
        budget: Total time allowed for the whole read. The filter calls this
            from inside a print job, so a printer that stopped answering must
            not hold the job up.

    Returns:
        The ATTR lines, or an empty list. Never raises: a printer that does not
        answer must not break a print job.
    """
    client = SnmpClient(
        host,
        community=community,
        timeout=timeout,
        deadline=time.monotonic() + budget,
    )
    try:
        markers = read_markers(client)
    except (SnmpError, OSError) as exc:
        logger.warning("supply report skipped for %s: %s", host, exc)
        return []
    return format_lines(markers)


def main() -> int:
    """Print the marker attributes for a printer, for use as a diagnostic."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s", stream=sys.stderr)
    if len(sys.argv) < 2:
        print(f"usage: {sys.argv[0]} <host> [community]", file=sys.stderr)
        return 2
    community = sys.argv[2] if len(sys.argv) > 2 else "public"
    lines = marker_lines(sys.argv[1], community)
    if not lines:
        print("no supply data", file=sys.stderr)
        return 1
    for line in lines:
        print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
