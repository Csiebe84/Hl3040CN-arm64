#!/usr/bin/env python3
"""Brother private-MIB supply decoding, ported from the Apache-2.0 `brother` library.

The Printer MIB (RFC 3805) reports ``prtMarkerSuppliesMaxCapacity = 0`` for this
printer's four toners, so a driver reading only that MIB has to publish ``-1``
for them. Brother's own agent exposes the real figures under
``1.3.6.1.4.1.2435…``.

The two OIDs that carry them:

``…5.5.8.0``   maintenance -- toner/drum/belt life, as a run of hex words
``…5.5.10.0``  counters    -- page counters, same layout

Each word is five bytes of hex: two characters naming the sensor and four bytes
of big-endian value. Percentage sensors are scaled by 100, so ``2710`` is 100 %.

This file is a port of ``brother/const.py`` and ``Brother._iterate_data`` from
the ``brother`` PyPI package (bieniu/brother), Apache-2.0. Only the tables the
HL-3040CN needs are kept; the ink tables and the status/localisation paths are
left out because this driver has no use for them. Apache-2.0 is compatible with
this project's GPL-3.0-or-later, and the attribution is repeated in the README.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

# Brother's private enterprise OID, shared by every model in this family.
BROTHER_ROOT = "1.3.6.1.4.1.2435.2.3.9.4.2.1.5.5"

OID_MAINTENANCE = f"{BROTHER_ROOT}.8.0"
OID_COUNTERS = f"{BROTHER_ROOT}.10.0"
OID_SERIAL = f"{BROTHER_ROOT}.1.0"
OID_FIRMWARE = f"{BROTHER_ROOT}.17.0"
OID_MODEL = "1.3.6.1.4.1.2435.2.3.9.1.1.7.0"

# Sensor word length: the newer firmware sends 14 hex characters (7 bytes of
# value), the older one 10 (5 bytes). See `Brother._legacy_printer`.
WORD_LENGTH = 14
LEGACY_WORD_LENGTH = 10


class Supply(StrEnum):
    """A supply this printer reports, named after its `marker-names` entry."""

    BLACK_TONER = "black_toner"
    CYAN_TONER = "cyan_toner"
    MAGENTA_TONER = "magenta_toner"
    YELLOW_TONER = "yellow_toner"
    BELT = "belt"
    BLACK_DRUM = "black_drum"
    CYAN_DRUM = "cyan_drum"
    MAGENTA_DRUM = "magenta_drum"
    YELLOW_DRUM = "yellow_drum"


# Sensor byte -> supply, from `VALUES_LASER_MAINTENANCE`. Only the *remaining
# life* sensors are listed. The printer also sends a raw toner value under
# `81`-`84` and a status code under `31`-`34`; neither is a percentage, so
# feeding them into `marker-levels` would misreport the cartridge.
_SENSOR_TO_SUPPLY: dict[str, Supply] = {
    "6f": Supply.BLACK_TONER,
    "70": Supply.CYAN_TONER,
    "71": Supply.MAGENTA_TONER,
    "72": Supply.YELLOW_TONER,
    # The `a1`-style aliases repeat the same percentage.
    "a1": Supply.BLACK_TONER,
    "a2": Supply.CYAN_TONER,
    "a3": Supply.MAGENTA_TONER,
    "a4": Supply.YELLOW_TONER,
    "69": Supply.BELT,
    "79": Supply.CYAN_DRUM,
    "7a": Supply.MAGENTA_DRUM,
    "7b": Supply.YELLOW_DRUM,
    "80": Supply.BLACK_DRUM,
}

# Sensor byte -> drum page counter. Kept apart from `_SENSOR_TO_SUPPLY` because
# a drum names two different figures: `79` is the life left in percent, while
# `73` is the number of pages that drum has printed.
_SENSOR_TO_DRUM_COUNTER: dict[str, Supply] = {
    "73": Supply.CYAN_DRUM,
    "74": Supply.MAGENTA_DRUM,
    "75": Supply.YELLOW_DRUM,
    "7e": Supply.BLACK_DRUM,
}

# The supplies whose word carries hundredths of a percent, so ``0a28`` is 26 %.
# This is the reference library's `PERCENT_VALUES`; everything else is a count.
_PERCENT_SUPPLIES = frozenset(
    {
        Supply.BLACK_TONER,
        Supply.CYAN_TONER,
        Supply.MAGENTA_TONER,
        Supply.YELLOW_TONER,
        Supply.BELT,
        Supply.BLACK_DRUM,
        Supply.CYAN_DRUM,
        Supply.MAGENTA_DRUM,
        Supply.YELLOW_DRUM,
    }
)

# Sensor byte -> page counter, from `VALUES_COUNTERS`.
_SENSOR_TO_COUNTER: dict[str, str] = {
    "00": "page_counter",
    "01": "bw_counter",
    "02": "color_counter",
    "06": "duplex_unit_pages_counter",
    "12": "black_counter",
    "13": "cyan_counter",
    "14": "magenta_counter",
    "15": "yellow_counter",
    "16": "image_counter",
}


def _is_legacy(blob: str) -> bool:
    """Return True for the 10-character word format.

    Ported from `Brother._legacy_printer`: the older firmware puts a literal
    ``14`` at every 10-character boundary.
    """
    if len(blob) < 20:
        return False
    marks = [blob[index - 2:index] == "14" for index in range(10, len(blob), 10)]
    return bool(marks) and all(marks)


def split_words(blob: str) -> tuple[list[str], bool]:
    """Split a hex payload into sensor words.

    Returns:
        The words and whether the legacy 10-character layout was used.
    """
    legacy = _is_legacy(blob)
    length = LEGACY_WORD_LENGTH if legacy else WORD_LENGTH
    return [blob[index:index + length] for index in range(0, len(blob), length)], legacy


def _decode_word(word: str, legacy: bool) -> tuple[str, int] | None:
    """Decode one sensor word into (sensor byte, hundredths of a percent).

    A modern word is ``SS`` (sensor) plus twelve hex characters, and the value
    is the last eight of them -- what the reference library reads with
    ``int(item[-8:], 16)``. Percentage sensors count hundredths, so ``0a28`` is
    26 %. A legacy word packs the value into one byte and the scale into the
    next, and the library multiplies by 100; that is normalised back to
    hundredths here so both layouts feed the same arithmetic.
    """
    if len(word) < 10:
        return None
    sensor = word[:2]
    try:
        if legacy:
            scale = int(word[8:10], 16)
            if not scale:
                return None
            return sensor, round(int(word[6:8], 16) / scale * 100) * 100
        return sensor, int(word[-8:], 16)
    except ValueError:
        return None


@dataclass(frozen=True)
class Supplies:
    """The supply state read from the printer."""

    percent: dict[Supply, int]
    counters: dict[str, int]
    drum_pages: dict[Supply, int]
    legacy: bool = False

    def get(self, supply: Supply) -> int | None:
        """Return the remaining life of *supply* in percent, or None."""
        return self.percent.get(supply)


def decode_supplies(maintenance: str, counters: str = "") -> Supplies:
    """Decode the maintenance and counter payloads.

    Args:
        maintenance: Hex payload of ``OID_MAINTENANCE``.
        counters: Hex payload of ``OID_COUNTERS``, if it was read.

    Returns:
        The decoded percentages, page counters and per-drum page counts.
        Percentages are clamped to 0..100: a few models put a raw count in a
        percentage sensor, and a value above 100 would read as a full tank when
        it actually means the drum is nearly worn out.
    """
    words, legacy = split_words(maintenance)
    percent: dict[Supply, int] = {}
    drum_pages: dict[Supply, int] = {}
    for word in words:
        decoded = _decode_word(word, legacy)
        if decoded is None:
            continue
        sensor, value = decoded
        if (supply := _SENSOR_TO_SUPPLY.get(sensor)) is not None:
            # Percentage sensors carry hundredths, so 0a28 is 26 %. Clamped
            # because a raw count in such a sensor would read as a full tank
            # when it really means the drum is nearly worn out.
            if supply in _PERCENT_SUPPLIES:
                value = round(value / 100)
            percent[supply] = max(0, min(100, value))
        elif (drum := _SENSOR_TO_DRUM_COUNTER.get(sensor)) is not None:
            drum_pages[drum] = value

    counter_values: dict[str, int] = {}
    if counters:
        counter_words, _ = split_words(counters)
        for word in counter_words:
            decoded = _decode_word(word, False)
            if decoded is None:
                continue
            sensor, value = decoded
            if (name := _SENSOR_TO_COUNTER.get(sensor)) is not None:
                counter_values[name] = value

    return Supplies(
        percent=percent,
        counters=counter_values,
        drum_pages=drum_pages,
        legacy=legacy,
    )


def as_bytes(payload: object) -> str:
    """Render an SNMP octet-string value as the hex text the decoder expects.

    Accepts the raw octets an SNMP read returns, or the already-split word list
    that the reference library's test fixtures use. The raw form ends in the
    agent's checksum byte, which is dropped; a word list has already been
    stripped, so it is only joined.
    """
    if isinstance(payload, (list, tuple)):
        return "".join(str(part) for part in payload)
    if isinstance(payload, bytes):
        data = payload
    elif isinstance(payload, str):
        data = payload.encode("latin-1", "replace")
    else:
        return ""
    return data.hex()[:-2]
