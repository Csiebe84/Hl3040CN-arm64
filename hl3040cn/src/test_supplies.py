#!/usr/bin/env python3
"""Tests for the supply reporting (snmp.py, brsupply.py, marker.py).

These run without the printer. The decoder is checked against real payloads
captured from other models of this family, whose expected values come from the
reference library's own snapshots -- so a change in the word layout shows up
here rather than as a wrong toner bar on the user's screen.

The SNMP transport is exercised against a real UDP socket on localhost that
speaks the protocol, not against a mock: a stubbed ``recvfrom`` would not catch
a malformed request, which is the failure this code is most likely to have.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import socket
import sys
import threading
import unittest
import unittest.mock
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import brsupply  # noqa: E402
import marker  # noqa: E402
import snmp  # noqa: E402
from brsupply import Supply  # noqa: E402

# Payloads from the reference library's fixtures (bieniu/brother, Apache-2.0).
# `dcp-l3550cdw` is a 14-character-word model, `mfc-5490cn` a legacy 10-character
# one, so both layouts are covered.
MODERN_MAINTENANCE = (
    "76010400000001" "790104000023f0" "7301040000064b" "77010400000001"
    "7a0104000023f0" "7401040000064b" "78010400000001" "7b0104000023f0"
    "7501040000064b" "7f010400000001" "800104000023f0" "7e01040000064b"
    "68010400000001" "55010400000001" "32010400000001" "700104000003e8"
    "8201040000000a" "33010400000002" "71010400000320" "8301040000000a"
    "34010400000002" "720104000000c8" "8401040000000a" "31010400000001"
    "6f010400000a28" "8101040000001e" "690104000025e4" "35010400000001"
    "6d010400002648" "54010400000001" "6a0104000025e4"
)
MODERN_COUNTERS = (
    "0001040000064b" "02010400000386" "010104000002c5"
    "0601040000021a" "080104000000ed" "0701040000012d"
)
LEGACY_MAINTENANCE = "a101020414a201020c14a301020614a401020b14"


def _len(n: int) -> bytes:
    """Independent BER length encoder, so the test does not lean on snmp.py."""
    if n < 0x80:
        return bytes([n])
    body = n.to_bytes((n.bit_length() + 7) // 8, "big")
    return bytes([0x80 | len(body)]) + body


def _tlv(tag: int, payload: bytes) -> bytes:
    """Independent TLV encoder for building reply packets."""
    return bytes([tag]) + _len(len(payload)) + payload


def _oid_body(dotted: str) -> bytes:
    """Independent OID content encoder."""
    parts = [int(p) for p in dotted.split(".")]
    body = bytes([parts[0] * 40 + parts[1]])
    for part in parts[2:]:
        if part < 0x80:
            body += bytes([part])
            continue
        chunk = [part & 0x7F]
        part >>= 7
        while part:
            chunk.append((part & 0x7F) | 0x80)
            part >>= 7
        body += bytes(reversed(chunk))
    return body


def _int_body(value: int) -> bytes:
    """Independent signed INTEGER content encoder."""
    length = max(1, (value.bit_length() + 8) // 8)
    return value.to_bytes(length, "big", signed=True)


def make_response(request_id: int, pairs: list[tuple[str, int, str]]) -> bytes:
    """Build a GetResponse for the given (oid, tag, value) triples."""
    varbinds = b""
    for oid, tag, value in pairs:
        if tag == 0x02:
            payload = _int_body(int(value))
        elif tag == 0x04:
            # Octet strings arrive either as text or as already-encoded bytes.
            payload = value if isinstance(value, bytes) else value.encode("latin-1")
        else:
            payload = value if isinstance(value, bytes) else str(value).encode()
        varbinds += _tlv(0x30, _tlv(0x06, _oid_body(oid)) + _tlv(tag, payload))
    pdu = _tlv(
        0xA2,
        _tlv(0x02, _int_body(request_id))
        + _tlv(0x02, _int_body(0))
        + _tlv(0x02, _int_body(0))
        + _tlv(0x30, varbinds),
    )
    return _tlv(0x30, _tlv(0x02, _int_body(0)) + _tlv(0x04, b"public") + pdu)


def read_oid(data: bytes, offset: int) -> str:
    """Read an OID out of a request packet, for the fake agent."""
    tag = data[offset]
    assert tag == 0x06, f"expected OID, got {tag:#04x}"
    length = data[offset + 1]
    body = data[offset + 2:offset + 2 + length]
    parts = [body[0] // 40, body[0] % 40]
    value = 0
    for byte in body[1:]:
        value = (value << 7) | (byte & 0x7F)
        if not byte & 0x80:
            parts.append(value)
            value = 0
    return ".".join(str(p) for p in parts)


def _read_tlv(data: bytes, pos: int) -> tuple[int, int, int]:
    """Return (tag, content_start, content_end) for the TLV at *pos*."""
    tag = data[pos]
    length = data[pos + 1]
    header = 2
    if length & 0x80:
        count = length & 0x7F
        header = 2 + count
        length = int.from_bytes(data[pos + 2:pos + 2 + count], "big")
    content = pos + header
    return tag, content, content + length


def _skip(data: bytes, pos: int) -> int:
    """Return the offset just past the TLV whose tag sits at *pos*."""
    return _read_tlv(data, pos)[2]


def _pdu_start(data: bytes) -> int:
    """Return the offset of the PDU tag in a request packet."""
    # The version and community live inside the outer SEQUENCE, so descend
    # into it first; skipping it would land past the end of the packet.
    _, inner, _ = _read_tlv(data, 0)
    pos = _skip(data, inner)                    # past the version INTEGER
    pos = _skip(data, pos)                      # past the community OCTET STRING
    return pos


def read_pdu_tag(data: bytes) -> int:
    """Return the PDU tag of a request packet, for the fake agent."""
    return data[_pdu_start(data)]


def read_request_id(data: bytes) -> int:
    """Read the request-id out of a request packet, for the fake agent."""
    _, pdu_content, _ = _read_tlv(data, _pdu_start(data))
    tag, content, end = _read_tlv(data, pdu_content)
    assert tag == 0x02, f"expected INTEGER, got {tag:#04x}"
    return int.from_bytes(data[content:end], "big", signed=True)


class FakeAgent:
    """A real UDP socket that answers SNMP v1, so the transport is covered."""

    def __init__(self, table: list[tuple[str, int, object]], *, error: int = 0) -> None:
        """Start a thread that serves *table* as an SNMP agent."""
        self.table = sorted(table, key=lambda row: [int(p) for p in row[0].split(".")])
        self.error = error
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.settimeout(0.2)
        self.port = self.sock.getsockname()[1]
        self.requests: list[tuple[int, str]] = []
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def _serve(self) -> None:
        while not self._stop.is_set():
            try:
                data, peer = self.sock.recvfrom(65535)
            except (TimeoutError, OSError):
                continue
            try:
                tag = read_pdu_tag(data)
                request_id = read_request_id(data)
                oid = self._first_oid(data)
            except Exception:
                # A packet this test agent cannot parse is not a reply.
                continue
            self.requests.append((request_id, oid))
            reply = self._reply(tag, request_id, oid)
            try:
                self.sock.sendto(reply, peer)
            except OSError:
                pass

    def _first_oid(self, data: bytes) -> str:
        """Return the first OID of the request's variable binding list."""
        _, pdu_content, _ = _read_tlv(data, _pdu_start(data))
        pos = pdu_content
        for _ in range(3):                      # request-id, status, index
            _, _, pos = _read_tlv(data, pos)
        _, varbind_list, _ = _read_tlv(data, pos)
        _, varbind, _ = _read_tlv(data, varbind_list)
        return read_oid(data, varbind)

    def _reply(self, tag: int, request_id: int, oid: str) -> bytes:
        if self.error:
            return make_response(request_id, [])
        if tag == 0xA0:  # GET
            for row_oid, row_tag, value in self.table:
                if row_oid == oid:
                    return make_response(request_id, [(row_oid, row_tag, value)])
            return make_response(request_id, [])
        # GETNEXT: the first row after the requested OID.
        wanted = [int(p) for p in oid.split(".")]
        for row_oid, row_tag, value in self.table:
            if [int(p) for p in row_oid.split(".")] > wanted:
                return make_response(request_id, [(row_oid, row_tag, value)])
        return make_response(request_id, [])

    def close(self) -> None:
        """Stop the agent thread and close the socket."""
        self._stop.set()
        self._thread.join(timeout=1.0)
        self.sock.close()


class BerEncodingTest(unittest.TestCase):
    """The BER encoder, against vectors that are fixed by the standards."""

    def test_known_oid_vector(self) -> None:
        # X.690 / RFC 1157: sysDescr.0 is 1.3.6.1.2.1.1.1.0 and encodes to
        # 06 08 2b 06 01 02 01 01 01 00.
        self.assertEqual(
            snmp.encode_oid("1.3.6.1.2.1.1.1.0"),
            bytes([0x06, 0x08, 0x2B, 0x06, 0x01, 0x02, 0x01, 0x01, 0x01, 0x00]),
        )

    def test_multi_byte_arc(self) -> None:
        # Brother's enterprise OID has a 2435 arc, which needs base-128.
        encoded = snmp.encode_oid("1.3.6.1.4.1.2435")
        self.assertEqual(snmp.decode_oid(encoded[2:]), "1.3.6.1.4.1.2435")

    def test_oid_roundtrip(self) -> None:
        for oid in (
            "1.3.6.1.2.1.43.11.1.1.6.1",
            "1.3.6.1.4.1.2435.2.3.9.4.2.1.5.5.8.0",
            "1.3.6.1.2.1.1.3.0",
        ):
            with self.subTest(oid=oid):
                self.assertEqual(snmp.decode_oid(snmp.encode_oid(oid)[2:]), oid)

    def test_short_oid_rejected(self) -> None:
        with self.assertRaises(snmp.SnmpError):
            snmp.encode_oid("1")

    def test_malformed_oid_rejected(self) -> None:
        with self.assertRaises(snmp.SnmpError):
            snmp.encode_oid("1.3.x")

    def test_positive_int_gets_no_sign_padding(self) -> None:
        self.assertEqual(snmp._encode_int(1), bytes([0x02, 0x01, 0x01]))
        self.assertEqual(snmp._encode_int(127), bytes([0x02, 0x01, 0x7F]))

    def test_high_bit_int_is_padded(self) -> None:
        # 128 would read back as -128 without the leading zero byte.
        self.assertEqual(snmp._encode_int(128), bytes([0x02, 0x02, 0x00, 0x80]))

    def test_zero_int(self) -> None:
        self.assertEqual(snmp._encode_int(0), bytes([0x02, 0x01, 0x00]))


class ResponseParseTest(unittest.TestCase):
    """Parsing a reply that the test built by hand, not by the module's encoder."""

    def test_octet_string_and_int(self) -> None:
        packet = make_response(
            42,
            [
                ("1.3.6.1.2.1.43.11.1.1.6.1", 0x04, "Black Toner Cartridge"),
                ("1.3.6.1.2.1.43.11.1.1.9.6", 0x02, 20617),
            ],
        )
        status, index, varbinds = snmp.parse_response(packet, 42)
        self.assertEqual((status, index), (0, 0))
        self.assertEqual(varbinds[0], ("1.3.6.1.2.1.43.11.1.1.6.1", b"Black Toner Cartridge"))
        self.assertEqual(varbinds[1], ("1.3.6.1.2.1.43.11.1.1.9.6", 20617))

    def test_request_id_mismatch_rejected(self) -> None:
        packet = make_response(1, [("1.3.6.1.2.1.1.3.0", 0x02, 5)])
        with self.assertRaises(snmp.SnmpError):
            snmp.parse_response(packet, 2)

    def test_truncated_packet_rejected(self) -> None:
        with self.assertRaises(snmp.SnmpError):
            snmp.parse_response(b"\x30\x82\x01", 1)

    def test_negative_level_is_signed(self) -> None:
        packet = make_response(7, [("1.3.6.1.2.1.43.11.1.1.9.1", 0x02, -3)])
        _, _, varbinds = snmp.parse_response(packet, 7)
        self.assertEqual(varbinds[0][1], -3)


class SupplyDecodeTest(unittest.TestCase):
    """The decoder, against the reference library's captured payloads."""

    def test_modern_percentages(self) -> None:
        supplies = brsupply.decode_supplies(MODERN_MAINTENANCE, MODERN_COUNTERS)
        self.assertFalse(supplies.legacy)
        self.assertEqual(
            supplies.percent,
            {
                Supply.BLACK_TONER: 26,
                Supply.CYAN_TONER: 10,
                Supply.MAGENTA_TONER: 8,
                Supply.YELLOW_TONER: 2,
                Supply.BELT: 97,
                Supply.BLACK_DRUM: 92,
                Supply.CYAN_DRUM: 92,
                Supply.MAGENTA_DRUM: 92,
                Supply.YELLOW_DRUM: 92,
            },
        )

    def test_modern_counters(self) -> None:
        supplies = brsupply.decode_supplies(MODERN_MAINTENANCE, MODERN_COUNTERS)
        self.assertEqual(
            supplies.counters,
            {
                "page_counter": 1611,
                "bw_counter": 709,
                "color_counter": 902,
                "duplex_unit_pages_counter": 538,
            },
        )

    def test_drum_page_counts_are_not_percentages(self) -> None:
        # `73` is the drum's page count, `79` its remaining life; mixing them up
        # would show a drum as 100 % full at 1611 pages.
        supplies = brsupply.decode_supplies(MODERN_MAINTENANCE, MODERN_COUNTERS)
        self.assertEqual(supplies.drum_pages[Supply.CYAN_DRUM], 1611)
        self.assertEqual(supplies.percent[Supply.CYAN_DRUM], 92)

    def test_legacy_layout(self) -> None:
        supplies = brsupply.decode_supplies(LEGACY_MAINTENANCE)
        self.assertTrue(supplies.legacy)
        # The library's arithmetic is item[6:8] / item[8:10] * 100, so the four
        # words decode to 04/14, 0c/14, 06/14, 0b/14 -> 20, 60, 30, 55.
        self.assertEqual(
            supplies.percent,
            {
                Supply.BLACK_TONER: 20,
                Supply.CYAN_TONER: 60,
                Supply.MAGENTA_TONER: 30,
                Supply.YELLOW_TONER: 55,
            },
        )

    def test_legacy_zero_scale_is_skipped(self) -> None:
        # A scale byte of 0 would divide by zero. The guard is on the decode
        # path, because a legacy payload always ends its words in "14".
        self.assertIsNone(brsupply._decode_word("a101020400", legacy=True))
        self.assertEqual(brsupply._decode_word("a201020c14", legacy=True),
                         ("a2", 6000))

    def test_empty_payload(self) -> None:
        supplies = brsupply.decode_supplies("")
        self.assertEqual(supplies.percent, {})
        self.assertEqual(supplies.counters, {})

    def test_out_of_range_percentage_is_clamped(self) -> None:
        # A raw count in a percentage sensor must not read as a full tank.
        supplies = brsupply.decode_supplies("6f01040000ffff")
        self.assertEqual(supplies.percent[Supply.BLACK_TONER], 100)

    def test_unknown_sensor_is_ignored(self) -> None:
        supplies = brsupply.decode_supplies("ff010400000064")
        self.assertEqual(supplies.percent, {})

    def test_odd_tail_does_not_raise(self) -> None:
        supplies = brsupply.decode_supplies(MODERN_MAINTENANCE + "6f01")
        self.assertEqual(supplies.percent[Supply.BLACK_TONER], 26)

    def test_as_bytes_from_raw_octets(self) -> None:
        # A raw read ends in the agent's checksum byte, which is dropped.
        self.assertEqual(brsupply.as_bytes(b"\x6f\x01\x04\x00\x00\x0a\x28\xff"), "6f010400000a28")

    def test_as_bytes_from_word_list(self) -> None:
        self.assertEqual(brsupply.as_bytes(["6f010400000a28", "70010400000a28"]),
                         "6f010400000a2870010400000a28")

    def test_as_bytes_of_none(self) -> None:
        self.assertEqual(brsupply.as_bytes(None), "")

    def test_oid_constants(self) -> None:
        self.assertEqual(brsupply.OID_MAINTENANCE, "1.3.6.1.4.1.2435.2.3.9.4.2.1.5.5.8.0")
        self.assertEqual(brsupply.OID_COUNTERS, "1.3.6.1.4.1.2435.2.3.9.4.2.1.5.5.10.0")


class ColorTest(unittest.TestCase):
    """Colour and toner-name mapping -- the part that fixes the swap."""

    def test_magenta_and_yellow_are_not_swapped(self) -> None:
        self.assertEqual(marker.color_for("Magenta Toner Cartridge"), "#FF00FF")
        self.assertEqual(marker.color_for("Yellow Toner Cartridge"), "#FFFF00")

    def test_black_and_cyan(self) -> None:
        self.assertEqual(marker.color_for("Black Toner Cartridge"), "#000000")
        self.assertEqual(marker.color_for("Cyan Toner Cartridge"), "#00FFFF")

    def test_colourless_supplies_are_none(self) -> None:
        self.assertEqual(marker.color_for("Waste Toner Box"), "none")
        self.assertEqual(marker.color_for("Belt Unit"), "none")

    def test_case_insensitive(self) -> None:
        self.assertEqual(marker.color_for("MAGENTA TONER CARTRIDGE"), "#FF00FF")

    def test_toner_key(self) -> None:
        self.assertIs(marker.toner_key("Magenta Toner Cartridge"), Supply.MAGENTA_TONER)
        self.assertIs(marker.toner_key("Yellow Toner Cartridge"), Supply.YELLOW_TONER)

    def test_non_toner_has_no_key(self) -> None:
        self.assertIsNone(marker.toner_key("Belt Unit"))
        self.assertIsNone(marker.toner_key("Black Drum Unit"))

    def test_quote_name_matches_cups_wrapping(self) -> None:
        self.assertEqual(marker.quote_name("Belt Unit"), "'\"Belt Unit\"'")

    def test_quote_name_escapes(self) -> None:
        self.assertEqual(marker.quote_name('a"b'), "'\"a\\\"b\"'")


class PercentTest(unittest.TestCase):
    """The level arithmetic, which must stay identical to CUPS' own."""

    def test_capacity_based(self) -> None:
        self.assertEqual(marker._percent(20617, 50000, "other"), 41)

    def test_level_is_already_a_percentage(self) -> None:
        self.assertEqual(marker._percent(27, 0, "opc"), 27)

    def test_no_capacity_and_no_percentage_type_is_unknown(self) -> None:
        self.assertEqual(marker._percent(-3, 0, "toner"), -1)

    def test_capacity_with_negative_level_is_unknown(self) -> None:
        self.assertEqual(marker._percent(-3, 50000, "toner"), -1)

    def test_result_is_clamped(self) -> None:
        self.assertEqual(marker._percent(99999, 100, "other"), 100)


class FormatTest(unittest.TestCase):
    """The emitted ATTR lines."""

    def markers(self) -> list[marker.Marker]:
        return [
            marker.Marker("Black Toner Cartridge", "toner", "#000000", 26),
            marker.Marker("Cyan Toner Cartridge", "toner", "#00FFFF", 10),
            marker.Marker("Magenta Toner Cartridge", "toner", "#FF00FF", 8),
            marker.Marker("Yellow Toner Cartridge", "toner", "#FFFF00", 2),
        ]

    def test_line_order_matches_cups(self) -> None:
        lines = marker.format_lines(self.markers())
        self.assertEqual([line.split("=")[0] for line in lines],
                         ["ATTR: marker-colors", "ATTR: marker-names",
                          "ATTR: marker-types", "ATTR: marker-levels"])

    def test_colors_line(self) -> None:
        self.assertEqual(marker.format_lines(self.markers())[0],
                         "ATTR: marker-colors=#000000,#00FFFF,#FF00FF,#FFFF00")

    def test_levels_line(self) -> None:
        self.assertEqual(marker.format_lines(self.markers())[3],
                         "ATTR: marker-levels=26,10,8,2")

    def test_empty_list_emits_nothing(self) -> None:
        self.assertEqual(marker.format_lines([]), [])

    def test_every_line_starts_with_the_cups_prefix(self) -> None:
        # scheduler/statbuf.c only recognises the "ATTR:" prefix.
        for line in marker.format_lines(self.markers()):
            self.assertTrue(line.startswith("ATTR: "))


class DeviceUriTest(unittest.TestCase):
    """Pulling the printer host out of the CUPS device URI."""

    def test_socket_uri(self) -> None:
        self.assertEqual(marker.host_from_device_uri("socket://192.168.178.50:9100"),
                         "192.168.178.50")

    def test_ipp_uri_with_path(self) -> None:
        self.assertEqual(marker.host_from_device_uri("ipp://printer.local/ipp/print"),
                         "printer.local")

    def test_uri_with_credentials(self) -> None:
        self.assertEqual(marker.host_from_device_uri("lpd://user:pw@10.0.0.5/queue"),
                         "10.0.0.5")

    def test_ipv6_uri(self) -> None:
        self.assertEqual(marker.host_from_device_uri("socket://[fd00::1]:9100"), "fd00::1")

    def test_local_uri_is_not_networked(self) -> None:
        self.assertIsNone(marker.host_from_device_uri("usb://Brother/HL-3040CN"))
        self.assertIsNone(marker.host_from_device_uri("/dev/usb/lp0"))


class AgentTest(unittest.TestCase):
    """The SNMP client against a real socket."""

    def setUp(self) -> None:
        self.agent = FakeAgent([
            ("1.3.6.1.2.1.43.11.1.1.6.1", 0x04, "Black Toner Cartridge"),
            ("1.3.6.1.2.1.43.11.1.1.6.2", 0x04, "Cyan Toner Cartridge"),
            ("1.3.6.1.2.1.43.11.1.1.9.1", 0x02, -3),
            ("1.3.6.1.2.1.43.11.1.1.9.2", 0x02, 10),
        ])
        self.client = snmp.SnmpClient("127.0.0.1", self.agent.port, timeout=1.0)

    def tearDown(self) -> None:
        self.agent.close()

    def test_get(self) -> None:
        values = self.client.get(["1.3.6.1.2.1.43.11.1.1.6.1"])
        self.assertEqual(values, [("1.3.6.1.2.1.43.11.1.1.6.1", b"Black Toner Cartridge")])

    def test_get_one(self) -> None:
        self.assertEqual(self.client.get_one("1.3.6.1.2.1.43.11.1.1.9.2"), 10)

    def test_walk_visits_the_whole_subtree(self) -> None:
        found = dict(self.client.walk("1.3.6.1.2.1.43.11.1.1.6"))
        self.assertEqual(found, {
            "1.3.6.1.2.1.43.11.1.1.6.1": b"Black Toner Cartridge",
            "1.3.6.1.2.1.43.11.1.1.6.2": b"Cyan Toner Cartridge",
        })

    def test_walk_stops_at_the_subtree_edge(self) -> None:
        found = self.client.walk("1.3.6.1.2.1.43.11.1.1.9")
        self.assertEqual([oid for oid, _ in found],
                         ["1.3.6.1.2.1.43.11.1.1.9.1", "1.3.6.1.2.1.43.11.1.1.9.2"])

    def test_request_ids_increase(self) -> None:
        self.client.get(["1.3.6.1.2.1.43.11.1.1.9.1"])
        self.client.get(["1.3.6.1.2.1.43.11.1.1.9.2"])
        ids = [request_id for request_id, _ in self.agent.requests]
        self.assertEqual(ids, sorted(ids))
        self.assertEqual(len(set(ids)), len(ids))

    def test_silent_agent_raises(self) -> None:
        # Nothing is listening on this port.
        client = snmp.SnmpClient("127.0.0.1", 1, timeout=0.1, retries=0)
        with self.assertRaises(snmp.SnmpError):
            client.get(["1.3.6.1.2.1.1.3.0"])

    def test_unknown_oid_returns_empty(self) -> None:
        self.assertEqual(self.client.get(["1.3.6.1.2.1.99.99"]), [])


class MarkerReadTest(unittest.TestCase):
    """End to end through the client: a fake printer answers the full read."""

    def setUp(self) -> None:
        self.agent = FakeAgent([
            ("1.3.6.1.2.1.43.11.1.1.6.1", 0x04, "Black Toner Cartridge"),
            ("1.3.6.1.2.1.43.11.1.1.6.2", 0x04, "Cyan Toner Cartridge"),
            ("1.3.6.1.2.1.43.11.1.1.6.3", 0x04, "Magenta Toner Cartridge"),
            ("1.3.6.1.2.1.43.11.1.1.6.4", 0x04, "Yellow Toner Cartridge"),
            ("1.3.6.1.2.1.43.11.1.1.6.6", 0x04, "Belt Unit"),
            ("1.3.6.1.2.1.43.11.1.1.5.1", 0x02, 3),
            ("1.3.6.1.2.1.43.11.1.1.5.6", 0x02, 1),
            ("1.3.6.1.2.1.43.11.1.1.9.1", 0x02, -3),
            ("1.3.6.1.2.1.43.11.1.1.9.6", 0x02, 20617),
            ("1.3.6.1.2.1.43.11.1.1.8.6", 0x02, 50000),
            (brsupply.OID_MAINTENANCE, 0x04, _raw_maintenance()),
            (brsupply.OID_COUNTERS, 0x04, _raw_counters()),
        ])
        self.client = snmp.SnmpClient("127.0.0.1", self.agent.port, timeout=1.0)

    def tearDown(self) -> None:
        self.agent.close()

    def test_read_markers(self) -> None:
        markers = marker.read_markers(self.client)
        names = [m.name for m in markers]
        self.assertEqual(names, [
            "Black Toner Cartridge", "Cyan Toner Cartridge",
            "Magenta Toner Cartridge", "Yellow Toner Cartridge", "Belt Unit",
        ])

    def test_toner_levels_come_from_the_private_mib(self) -> None:
        markers = {m.name: m for m in marker.read_markers(self.client)}
        # The standard MIB reports -3 for these; the private MIB has the truth.
        self.assertEqual(markers["Black Toner Cartridge"].level, 26)
        self.assertEqual(markers["Magenta Toner Cartridge"].level, 8)
        self.assertEqual(markers["Yellow Toner Cartridge"].level, 2)

    def test_belt_level_comes_from_the_standard_mib(self) -> None:
        markers = {m.name: m for m in marker.read_markers(self.client)}
        self.assertEqual(markers["Belt Unit"].level, 41)
        self.assertEqual(markers["Belt Unit"].color, "none")

    def test_colours_are_not_swapped(self) -> None:
        markers = {m.name: m for m in marker.read_markers(self.client)}
        self.assertEqual(markers["Magenta Toner Cartridge"].color, "#FF00FF")
        self.assertEqual(markers["Yellow Toner Cartridge"].color, "#FFFF00")

    def test_types(self) -> None:
        markers = {m.name: m for m in marker.read_markers(self.client)}
        self.assertEqual(markers["Black Toner Cartridge"].type, "toner")
        self.assertEqual(markers["Belt Unit"].type, "other")

    def test_unreachable_printer_yields_no_lines(self) -> None:
        # A printer that does not answer must not break the job.
        self.assertEqual(marker.marker_lines("127.0.0.1", timeout=0.1), [])

    def test_marker_lines_end_to_end(self) -> None:
        client = snmp.SnmpClient("127.0.0.1", self.agent.port, timeout=1.0)
        lines = marker.format_lines(marker.read_markers(client))
        self.assertEqual(lines[0],
                         "ATTR: marker-colors=#000000,#00FFFF,#FF00FF,#FFFF00,none")
        self.assertEqual(lines[3], "ATTR: marker-levels=26,10,8,2,41")


def _raw_maintenance() -> str:
    """The maintenance payload as raw octets, with the checksum byte."""
    return bytes.fromhex(MODERN_MAINTENANCE + "ff")


def _raw_counters() -> str:
    """The counter payload as raw octets, with the checksum byte."""
    return bytes.fromhex(MODERN_COUNTERS + "ff")


class FilterWiringTest(unittest.TestCase):
    """The filter's own reporting path, from DEVICE_URI to the ATTR lines.

    This is the integration the fix actually depends on: CUPS hands the filter a
    device URI, the filter has to find the printer's address in it, read the
    supplies and write the lines to stderr. Everything in between is stubbed by
    a real SNMP agent on localhost, so a broken pipe or a wrong environment
    variable shows up here rather than as an unchanged toner bar.
    """

    def setUp(self) -> None:
        self.agent = FakeAgent([
            ("1.3.6.1.2.1.43.11.1.1.6.1", 0x04, "Black Toner Cartridge"),
            ("1.3.6.1.2.1.43.11.1.1.6.2", 0x04, "Cyan Toner Cartridge"),
            ("1.3.6.1.2.1.43.11.1.1.6.3", 0x04, "Magenta Toner Cartridge"),
            ("1.3.6.1.2.1.43.11.1.1.6.4", 0x04, "Yellow Toner Cartridge"),
            ("1.3.6.1.2.1.43.11.1.1.6.6", 0x04, "Belt Unit"),
            ("1.3.6.1.2.1.43.11.1.1.5.1", 0x02, 3),
            ("1.3.6.1.2.1.43.11.1.1.5.6", 0x02, 1),
            ("1.3.6.1.2.1.43.11.1.1.9.1", 0x02, -3),
            ("1.3.6.1.2.1.43.11.1.1.9.6", 0x02, 20617),
            ("1.3.6.1.2.1.43.11.1.1.8.6", 0x02, 50000),
            (brsupply.OID_MAINTENANCE, 0x04, bytes.fromhex(MODERN_MAINTENANCE + "ff")),
            (brsupply.OID_COUNTERS, 0x04, bytes.fromhex(MODERN_COUNTERS + "ff")),
        ])
        self.filter = _load_filter()

    def tearDown(self) -> None:
        self.agent.close()

    def report(self, device_uri: str) -> list[str]:
        """Run the filter's supply report and return what it wrote to stderr."""
        captured = io.StringIO()
        original = snmp.SnmpClient.__init__

        def patched(instance, host, port=snmp.DEFAULT_PORT, **kwargs):
            # The fake agent listens on 127.0.0.1 on a random port; the host the
            # filter extracted is asserted separately, by DeviceUriTest.
            original(instance, "127.0.0.1", self.agent.port, **kwargs)

        snmp.SnmpClient.__init__ = patched
        try:
            with unittest.mock.patch.dict(os.environ, {"DEVICE_URI": device_uri}):
                with contextlib.redirect_stderr(captured):
                    self.filter.report_supplies()
        finally:
            snmp.SnmpClient.__init__ = original
        return [line for line in captured.getvalue().splitlines() if line.startswith("ATTR:")]

    def test_socket_uri_produces_all_four_lines(self) -> None:
        lines = self.report("socket://192.168.178.50:9100")
        self.assertEqual(len(lines), 4)
        self.assertEqual([line.split("=")[0] for line in lines],
                         ["ATTR: marker-colors", "ATTR: marker-names",
                          "ATTR: marker-types", "ATTR: marker-levels"])

    def test_colors_and_names_stay_in_step(self) -> None:
        lines = self.report("socket://192.168.178.50:9100")
        colors = lines[0].split("=", 1)[1].split(",")
        names = lines[1].split("=", 1)[1].split("',")
        self.assertEqual(colors[:5], ["#000000", "#00FFFF", "#FF00FF", "#FFFF00", "none"])
        # The name at each position must name the colour at the same position.
        self.assertIn("Magenta", names[2])
        self.assertIn("Yellow", names[3])

    def test_toner_levels_are_reported(self) -> None:
        lines = self.report("socket://192.168.178.50:9100")
        self.assertEqual(lines[3].split("=", 1)[1], "26,10,8,2,41")

    def test_non_network_uri_reports_nothing(self) -> None:
        self.assertEqual(self.report("usb://Brother/HL-3040CN"), [])

    def test_missing_device_uri_reports_nothing(self) -> None:
        captured = io.StringIO()
        with unittest.mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("DEVICE_URI", None)
            with contextlib.redirect_stderr(captured):
                self.filter.report_supplies()
        self.assertEqual([l for l in captured.getvalue().splitlines()
                          if l.startswith("ATTR:")], [])

    def test_unreachable_printer_does_not_raise(self) -> None:
        self.agent.close()
        # The printer is gone; the job must still be able to run.
        self.assertEqual(self.report("socket://127.0.0.1:9100"), [])


def _load_filter():
    """Import the CUPS filter, which has no .py suffix."""
    import importlib.machinery
    import importlib.util

    path = Path(__file__).resolve().parent.parent / "cups" / "brhl3040cn-filter"
    loader = importlib.machinery.SourceFileLoader("brhl3040cn_filter_under_test", str(path))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


if __name__ == "__main__":
    unittest.main()
