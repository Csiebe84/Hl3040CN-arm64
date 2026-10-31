#!/usr/bin/env python3
"""Minimal SNMP v1 client (RFC 1157) on the standard library only.

Why this exists: CUPS' ``socket``/``lpd`` backends read supply levels through
libcups, which implements the Printer MIB (RFC 3805) and nothing else. In that
MIB this printer reports ``prtMarkerSuppliesMaxCapacity = 0`` for all four
toners, so CUPS can only publish ``-1`` for them. The real figures live in
Brother's private MIB (``1.3.6.1.4.1.2435…``). Reading those needs SNMP, and
the board has no ``pysnmp`` -- so the two operations the driver needs, GET and a
GETNEXT walk, are implemented here.

Only SNMP v1 is supported: it is what the printer answers, it needs no
engine/discovery handshake, and its BER encoding is small enough to write out.
"""

from __future__ import annotations

import socket
import time

DEFAULT_PORT = 161
DEFAULT_COMMUNITY = "public"
DEFAULT_TIMEOUT = 1.0
DEFAULT_RETRIES = 1

# ASN.1/BER tags (X.690) and SNMP PDU tags (RFC 1157).
_TAG_INTEGER = 0x02
_TAG_OCTET_STRING = 0x04
_TAG_NULL = 0x05
_TAG_OID = 0x06
_TAG_SEQUENCE = 0x30
_TAG_IP_ADDRESS = 0x40
_TAG_COUNTER = 0x41
_TAG_GAUGE = 0x42
_TAG_TIME_TICKS = 0x43
_TAG_GET_REQUEST = 0xA0
_TAG_GET_NEXT_REQUEST = 0xA1
_TAG_GET_RESPONSE = 0xA2

# SNMP error-status values (RFC 1157, section 4.1.2).
ERR_NO_SUCH_NAME = 2

_SIGNED_TAGS = frozenset({_TAG_INTEGER})
_UNSIGNED_TAGS = frozenset({_TAG_COUNTER, _TAG_GAUGE, _TAG_TIME_TICKS})

# The largest datagram worth reading back; a supply walk never comes close.
_MAX_DATAGRAM = 65535


class SnmpError(Exception):
    """The printer did not answer, or answered with an SNMP error."""


def _encode_length(length: int) -> bytes:
    """Encode a BER length field, short or long form."""
    if length < 0x80:
        return bytes([length])
    body = b""
    while length:
        body = bytes([length & 0xFF]) + body
        length >>= 8
    return bytes([0x80 | len(body)]) + body


def _tlv(tag: int, payload: bytes) -> bytes:
    """Wrap *payload* in a tag/length/value triple."""
    return bytes([tag]) + _encode_length(len(payload)) + payload


def _encode_int(value: int) -> bytes:
    """Encode a signed BER INTEGER (two's complement, minimal length)."""
    if value == 0:
        return _tlv(_TAG_INTEGER, b"\x00")
    body = b""
    remaining = value
    while remaining > 0:
        body = bytes([remaining & 0xFF]) + body
        remaining >>= 8
    # A leading set bit would read back as negative, so pad with a zero byte.
    if body[0] & 0x80:
        body = b"\x00" + body
    return _tlv(_TAG_INTEGER, body)


def encode_oid(dotted: str) -> bytes:
    """Encode a dotted OID string as a BER OBJECT IDENTIFIER.

    Raises:
        SnmpError: If the OID has fewer than two components or a bad component.
    """
    try:
        parts = [int(part) for part in dotted.split(".")]
    except ValueError as exc:
        raise SnmpError(f"malformed OID {dotted!r}") from exc
    if len(parts) < 2:
        raise SnmpError(f"OID needs at least two components: {dotted!r}")

    # The first two arcs share one byte as 40 * X + Y.
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
    return _tlv(_TAG_OID, body)


def decode_oid(body: bytes) -> str:
    """Decode the contents of a BER OBJECT IDENTIFIER into dotted form."""
    if not body:
        raise SnmpError("empty OID")
    first = body[0]
    parts = [first // 40, first % 40]
    value = 0
    for byte in body[1:]:
        value = (value << 7) | (byte & 0x7F)
        if not byte & 0x80:
            parts.append(value)
            value = 0
    return ".".join(str(part) for part in parts)


def decode_int(body: bytes, *, signed: bool) -> int:
    """Decode a BER INTEGER body; empty is zero."""
    if not body:
        return 0
    return int.from_bytes(body, "big", signed=signed and bool(body[0] & 0x80))


def _read_tlv(data: bytes, pos: int) -> tuple[int, bytes, int]:
    """Read one tag/length/value triple, returning it and the next offset."""
    if pos + 2 > len(data):
        raise SnmpError("truncated TLV")
    tag = data[pos]
    length = data[pos + 1]
    pos += 2
    if length & 0x80:
        count = length & 0x7F
        if count == 0 or pos + count > len(data):
            raise SnmpError("bad length field")
        length = int.from_bytes(data[pos:pos + count], "big")
        pos += count
    end = pos + length
    if end > len(data):
        raise SnmpError("TLV runs past the end of the packet")
    return tag, data[pos:end], end


def _parse_varbinds(body: bytes) -> list[tuple[str, object]]:
    """Parse a VarBindList into (oid, value) pairs."""
    pairs: list[tuple[str, object]] = []
    pos = 0
    while pos < len(body):
        tag, item, pos = _read_tlv(body, pos)
        if tag != _TAG_SEQUENCE:
            raise SnmpError("variable binding is not a SEQUENCE")
        _, name, offset = _read_tlv(item, 0)
        value_tag, value, _ = _read_tlv(item, offset)
        oid = decode_oid(name)
        if value_tag in _SIGNED_TAGS:
            pairs.append((oid, decode_int(value, signed=True)))
        elif value_tag in _UNSIGNED_TAGS:
            pairs.append((oid, decode_int(value, signed=False)))
        elif value_tag == _TAG_OCTET_STRING:
            pairs.append((oid, value))
        elif value_tag == _TAG_OID:
            pairs.append((oid, decode_oid(value)))
        elif value_tag == _TAG_NULL:
            pairs.append((oid, None))
        elif value_tag == _TAG_IP_ADDRESS:
            pairs.append((oid, ".".join(str(byte) for byte in value)))
        else:
            pairs.append((oid, value))
    return pairs


def build_request(tag: int, oids: list[str], request_id: int, community: str) -> bytes:
    """Build a complete SNMP v1 GET or GETNEXT message."""
    varbinds = b"".join(
        _tlv(_TAG_SEQUENCE, encode_oid(oid) + _tlv(_TAG_NULL, b"")) for oid in oids
    )
    pdu = _tlv(
        tag,
        _encode_int(request_id)
        + _encode_int(0)  # error-status
        + _encode_int(0)  # error-index
        + _tlv(_TAG_SEQUENCE, varbinds),
    )
    return _tlv(
        _TAG_SEQUENCE,
        _encode_int(0)  # version 0 is SNMPv1
        + _tlv(_TAG_OCTET_STRING, community.encode("ascii", "replace"))
        + pdu,
    )


def parse_response(packet: bytes, request_id: int) -> tuple[int, int, list[tuple[str, object]]]:
    """Parse a GetResponse into (error-status, error-index, variable bindings)."""
    tag, body, _ = _read_tlv(packet, 0)
    if tag != _TAG_SEQUENCE:
        raise SnmpError("response is not a SEQUENCE")

    _, version, pos = _read_tlv(body, 0)
    _, _, pos = _read_tlv(body, pos)
    pdu_tag, pdu, _ = _read_tlv(body, pos)
    if pdu_tag != _TAG_GET_RESPONSE:
        raise SnmpError(f"unexpected PDU tag {pdu_tag:#04x}")
    if decode_int(version, signed=True) != 0:
        raise SnmpError("response is not SNMPv1")

    _, raw_id, offset = _read_tlv(pdu, 0)
    _, raw_status, offset = _read_tlv(pdu, offset)
    _, raw_index, offset = _read_tlv(pdu, offset)
    _, varbind_list, offset = _read_tlv(pdu, offset)

    if decode_int(raw_id, signed=True) != request_id:
        raise SnmpError("response request-id does not match the request")
    return (
        decode_int(raw_status, signed=True),
        decode_int(raw_index, signed=True),
        _parse_varbinds(varbind_list),
    )


class SnmpClient:
    """A synchronous SNMP v1 client for one agent."""

    def __init__(
        self,
        host: str,
        port: int = DEFAULT_PORT,
        community: str = DEFAULT_COMMUNITY,
        timeout: float = DEFAULT_TIMEOUT,
        retries: int = DEFAULT_RETRIES,
        deadline: float | None = None,
    ) -> None:
        """Store the agent address and the retry policy.

        Args:
            deadline: An absolute ``time.monotonic()`` value after which no
                further request is sent. The filter runs inside a print job, so
                a printer that has gone away must not hold the job up.
        """
        self.host = host
        self.port = port
        self.community = community
        self.timeout = timeout
        self.retries = retries
        self.deadline = deadline
        self._request_id = 0

    def _next_request_id(self) -> int:
        """Return the next request id, kept in the positive 31-bit range."""
        self._request_id = (self._request_id + 1) & 0x7FFFFFFF
        return self._request_id

    def _exchange(self, packet: bytes, request_id: int) -> tuple[int, int, list[tuple[str, object]]]:
        """Send *packet* and parse the reply, retrying only on timeouts."""
        failure: OSError | None = None
        for _ in range(self.retries + 1):
            if self.deadline is not None:
                remaining = self.deadline - time.monotonic()
                if remaining <= 0:
                    raise SnmpError(f"time budget for {self.host} exhausted")
            else:
                remaining = self.timeout
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                    sock.settimeout(min(self.timeout, remaining))
                    sock.sendto(packet, (self.host, self.port))
                    response, _ = sock.recvfrom(_MAX_DATAGRAM)
            except OSError as exc:
                failure = exc
                continue
            return parse_response(response, request_id)
        raise SnmpError(f"no answer from {self.host}: {failure}")

    def _request(self, tag: int, oids: list[str]) -> tuple[int, int, list[tuple[str, object]]]:
        """Issue one GET or GETNEXT and return the raw response fields."""
        request_id = self._next_request_id()
        packet = build_request(tag, oids, request_id, self.community)
        return self._exchange(packet, request_id)

    def get(self, oids: list[str]) -> list[tuple[str, object]]:
        """Read the given OIDs.

        Raises:
            SnmpError: On a timeout, a malformed reply, or any error-status.
        """
        status, index, varbinds = self._request(_TAG_GET_REQUEST, list(oids))
        if status:
            raise SnmpError(f"agent error {status} at variable binding {index}")
        return varbinds

    def get_one(self, oid: str) -> object:
        """Read a single OID and return its value.

        Raises:
            SnmpError: If the agent does not answer with that OID. A printer
                that omits an optional object is not an error worth crashing
                on, but a caller reading one value does need to know.
        """
        values = self.get([oid])
        if not values:
            raise SnmpError(f"{self.host} did not return {oid}")
        return values[0][1]

    def walk(self, root: str) -> list[tuple[str, object]]:
        """Walk the subtree at *root* with GETNEXT until it is left.

        The walk stops at the end of the MIB (error-status ``noSuchName``), when
        the agent stops making progress, or when the returned OID leaves the
        subtree. Any other error is raised.

        Raises:
            SnmpError: On a timeout, a malformed reply, or a real agent error.
        """
        prefix = root.split(".")
        current = root
        results: list[tuple[str, object]] = []
        while True:
            status, _, varbinds = self._request(_TAG_GET_NEXT_REQUEST, [current])
            if status == ERR_NO_SUCH_NAME:
                break
            if status:
                raise SnmpError(f"agent error {status} while walking {root}")
            if not varbinds:
                break
            oid, value = varbinds[0]
            parts = oid.split(".")
            if parts[:len(prefix)] != prefix or oid == current:
                break
            results.append((oid, value))
            current = oid
        return results
