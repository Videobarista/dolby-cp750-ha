"""Minimal SNMP v1/v2c client (GET and GETNEXT) for reading the CP750 status MIB.

Only what the integration needs is implemented: BER encoding of requests,
decoding of responses, and one UDP exchange per request. Doing this here keeps
the integration free of extra requirements.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import Enum
import logging
import secrets
from typing import Any

_LOGGER = logging.getLogger(__name__)

SNMP_V1 = 0
SNMP_V2C = 1
VERSION_NAMES = {SNMP_V1: "1", SNMP_V2C: "2c"}
VERSIONS_BY_NAME = {name: version for version, name in VERSION_NAMES.items()}

DEFAULT_TIMEOUT = 1.5
DEFAULT_RETRIES = 1

# BER / SNMP tags
_INTEGER = 0x02
_OCTET_STRING = 0x04
_NULL = 0x05
_OID = 0x06
_SEQUENCE = 0x30
_IP_ADDRESS = 0x40
_COUNTER32 = 0x41
_GAUGE32 = 0x42
_TIMETICKS = 0x43
_OPAQUE = 0x44
_COUNTER64 = 0x46
_NO_SUCH_OBJECT = 0x80
_NO_SUCH_INSTANCE = 0x81
_END_OF_MIB_VIEW = 0x82

PDU_GET = 0xA0
PDU_GET_NEXT = 0xA1
PDU_RESPONSE = 0xA2

_ERROR_NO_SUCH_NAME = 2


class SnmpError(Exception):
    """SNMP request failed."""


class SnmpTimeoutError(SnmpError):
    """No SNMP response arrived in time."""


class NoValue(Enum):
    """Exception values an agent returns instead of a value (SNMPv2c)."""

    NO_SUCH_OBJECT = _NO_SUCH_OBJECT
    NO_SUCH_INSTANCE = _NO_SUCH_INSTANCE
    END_OF_MIB_VIEW = _END_OF_MIB_VIEW


@dataclass(frozen=True, slots=True)
class TimeTicks:
    """TimeTicks value, in hundredths of a second."""

    value: int


@dataclass(frozen=True, slots=True)
class SnmpMessage:
    """A decoded SNMP message."""

    version: int
    community: str
    pdu_type: int
    request_id: int
    error_status: int
    error_index: int
    varbinds: list[tuple[str, Any]]


# ---------------------------------------------------------------------------
# Encoding
# ---------------------------------------------------------------------------


def _encode_length(length: int) -> bytes:
    if length < 0x80:
        return bytes([length])
    body = length.to_bytes((length.bit_length() + 7) // 8, "big")
    return bytes([0x80 | len(body)]) + body


def _tlv(tag: int, payload: bytes) -> bytes:
    return bytes([tag]) + _encode_length(len(payload)) + payload


def _encode_integer(value: int, tag: int = _INTEGER) -> bytes:
    length = max(1, (value.bit_length() + 8) // 8)
    return _tlv(tag, value.to_bytes(length, "big", signed=True))


def _encode_unsigned(value: int, tag: int) -> bytes:
    body = value.to_bytes(max(1, (value.bit_length() + 7) // 8), "big")
    if body[0] & 0x80:
        body = b"\x00" + body
    return _tlv(tag, body)


def _base128(value: int) -> bytes:
    out = [value & 0x7F]
    value >>= 7
    while value:
        out.append(0x80 | (value & 0x7F))
        value >>= 7
    return bytes(reversed(out))


def encode_oid(oid: str) -> bytes:
    """Encode a dotted OID string."""
    try:
        arcs = [int(part) for part in oid.strip(".").split(".")]
    except ValueError as err:
        raise ValueError(f"Invalid OID {oid!r}") from err
    if len(arcs) < 2 or arcs[0] > 2 or (arcs[0] < 2 and arcs[1] >= 40) or min(arcs) < 0:
        raise ValueError(f"Invalid OID {oid!r}")
    body = _base128(40 * arcs[0] + arcs[1]) + b"".join(_base128(arc) for arc in arcs[2:])
    return _tlv(_OID, body)


def _encode_value(value: Any) -> bytes:
    if value is None:
        return _tlv(_NULL, b"")
    if isinstance(value, NoValue):
        return _tlv(value.value, b"")
    if isinstance(value, TimeTicks):
        return _encode_unsigned(value.value, _TIMETICKS)
    if isinstance(value, bool):
        raise TypeError("bool is not an SNMP type")
    if isinstance(value, int):
        return _encode_integer(value)
    if isinstance(value, str):
        return _tlv(_OCTET_STRING, value.encode("latin-1"))
    if isinstance(value, bytes):
        return _tlv(_OCTET_STRING, value)
    raise TypeError(f"Cannot encode {type(value).__name__} as an SNMP value")


def encode_message(
    *,
    version: int,
    community: str,
    pdu_type: int,
    request_id: int,
    varbinds: Sequence[tuple[str, Any]],
    error_status: int = 0,
    error_index: int = 0,
) -> bytes:
    """Encode a complete SNMP message."""
    bindings = b"".join(
        _tlv(_SEQUENCE, encode_oid(oid) + _encode_value(value)) for oid, value in varbinds
    )
    pdu = _tlv(
        pdu_type,
        _encode_integer(request_id)
        + _encode_integer(error_status)
        + _encode_integer(error_index)
        + _tlv(_SEQUENCE, bindings),
    )
    return _tlv(
        _SEQUENCE,
        _encode_integer(version) + _tlv(_OCTET_STRING, community.encode("latin-1")) + pdu,
    )


# ---------------------------------------------------------------------------
# Decoding
# ---------------------------------------------------------------------------


def _read_tlv(data: bytes, pos: int) -> tuple[int, bytes, int]:
    """Return (tag, value, position after the element)."""
    if pos + 2 > len(data):
        raise SnmpError("Truncated SNMP message")
    tag = data[pos]
    length = data[pos + 1]
    pos += 2
    if length & 0x80:
        count = length & 0x7F
        if count == 0 or count > 4 or pos + count > len(data):
            raise SnmpError("Unsupported length encoding in SNMP message")
        length = int.from_bytes(data[pos : pos + count], "big")
        pos += count
    end = pos + length
    if end > len(data):
        raise SnmpError("Truncated SNMP message")
    return tag, data[pos:end], end


def decode_oid(body: bytes) -> str:
    """Decode the content octets of an OID."""
    if not body:
        raise SnmpError("Empty OID")
    values: list[int] = []
    current = 0
    for byte in body:
        current = (current << 7) | (byte & 0x7F)
        if not byte & 0x80:
            values.append(current)
            current = 0
    if body[-1] & 0x80:
        raise SnmpError("Truncated OID")
    first = values[0]
    if first < 40:
        arcs = [0, first]
    elif first < 80:
        arcs = [1, first - 40]
    else:
        arcs = [2, first - 80]
    return ".".join(str(arc) for arc in arcs + values[1:])


def _decode_value(tag: int, body: bytes) -> Any:
    if tag == _INTEGER:
        return int.from_bytes(body, "big", signed=True) if body else 0
    if tag in (_OCTET_STRING, _OPAQUE):
        return bytes(body)
    if tag == _NULL:
        return None
    if tag == _OID:
        return decode_oid(body)
    if tag == _IP_ADDRESS:
        return ".".join(str(byte) for byte in body)
    if tag == _TIMETICKS:
        return TimeTicks(int.from_bytes(body, "big"))
    if tag in (_COUNTER32, _GAUGE32, _COUNTER64):
        return int.from_bytes(body, "big")
    if tag in (_NO_SUCH_OBJECT, _NO_SUCH_INSTANCE, _END_OF_MIB_VIEW):
        return NoValue(tag)
    raise SnmpError(f"Unsupported SNMP value type 0x{tag:02x}")


def _expect(data: bytes, pos: int, tag: int) -> tuple[bytes, int]:
    found, body, pos = _read_tlv(data, pos)
    if found != tag:
        raise SnmpError(f"Expected tag 0x{tag:02x}, found 0x{found:02x}")
    return body, pos


def decode_message(data: bytes) -> SnmpMessage:
    """Decode an SNMP v1/v2c message."""
    message, _ = _expect(data, 0, _SEQUENCE)
    version_raw, pos = _expect(message, 0, _INTEGER)
    community_raw, pos = _expect(message, pos, _OCTET_STRING)
    pdu_type, pdu, _ = _read_tlv(message, pos)
    if pdu_type not in (PDU_GET, PDU_GET_NEXT, PDU_RESPONSE):
        raise SnmpError(f"Unsupported PDU type 0x{pdu_type:02x}")
    request_id_raw, pos = _expect(pdu, 0, _INTEGER)
    error_status_raw, pos = _expect(pdu, pos, _INTEGER)
    error_index_raw, pos = _expect(pdu, pos, _INTEGER)
    bindings, _ = _expect(pdu, pos, _SEQUENCE)

    varbinds: list[tuple[str, Any]] = []
    pos = 0
    while pos < len(bindings):
        binding, pos = _expect(bindings, pos, _SEQUENCE)
        oid_raw, inner = _expect(binding, 0, _OID)
        tag, value_raw, _ = _read_tlv(binding, inner)
        varbinds.append((decode_oid(oid_raw), _decode_value(tag, value_raw)))

    return SnmpMessage(
        version=int.from_bytes(version_raw, "big", signed=True),
        community=community_raw.decode("latin-1"),
        pdu_type=pdu_type,
        request_id=int.from_bytes(request_id_raw, "big", signed=True),
        error_status=int.from_bytes(error_status_raw, "big", signed=True),
        error_index=int.from_bytes(error_index_raw, "big", signed=True),
        varbinds=varbinds,
    )


def as_text(value: Any) -> str | None:
    """Return an OCTET STRING value as text (NUL bytes and padding removed)."""
    if isinstance(value, bytes):
        return value.decode("ascii", errors="replace").replace("\x00", "").strip()
    if isinstance(value, str):
        return value.strip()
    return None


def oid_in_subtree(oid: str, root: str) -> bool:
    """Return True if ``oid`` lies below ``root``."""
    return oid.startswith(root.rstrip(".") + ".")


# ---------------------------------------------------------------------------
# Transport
# ---------------------------------------------------------------------------


class _SnmpProtocol(asyncio.DatagramProtocol):
    """Receive the response that matches one request ID."""

    def __init__(self) -> None:
        self.request_id = 0
        self.future: asyncio.Future[SnmpMessage] | None = None

    def datagram_received(self, data: bytes, addr: Any) -> None:
        future = self.future
        if future is None or future.done():
            return
        try:
            message = decode_message(data)
        except SnmpError as err:
            _LOGGER.debug("Ignoring undecodable SNMP datagram from %s: %s", addr, err)
            return
        if message.pdu_type != PDU_RESPONSE or message.request_id != self.request_id:
            _LOGGER.debug("Ignoring SNMP datagram for another request from %s", addr)
            return
        future.set_result(message)

    def error_received(self, exc: Exception) -> None:
        future = self.future
        if future is not None and not future.done():
            future.set_exception(SnmpError(f"Network error: {exc}"))


type EndpointFactory = Callable[..., Any]


async def _create_endpoint(
    loop: asyncio.AbstractEventLoop,
    factory: Callable[[], asyncio.DatagramProtocol],
    host: str,
    port: int,
) -> asyncio.DatagramTransport:
    """Open a connected UDP socket."""
    transport, _ = await loop.create_datagram_endpoint(factory, remote_addr=(host, port))
    return transport


class SnmpClient:
    """Read values from one SNMP agent."""

    def __init__(
        self,
        host: str,
        community: str,
        *,
        version: int = SNMP_V2C,
        port: int = 161,
        timeout: float = DEFAULT_TIMEOUT,
        retries: int = DEFAULT_RETRIES,
        endpoint_factory: EndpointFactory | None = None,
    ) -> None:
        """Initialize the client."""
        self.host = host
        self.community = community
        self.version = version
        self.port = port
        self._timeout = timeout
        self._retries = retries
        self._endpoint_factory = endpoint_factory or _create_endpoint

    async def _exchange(self, pdu_type: int, oids: Sequence[str]) -> SnmpMessage:
        """Send one request and wait for the matching response."""
        loop = asyncio.get_running_loop()
        protocol = _SnmpProtocol()
        try:
            transport = await self._endpoint_factory(loop, lambda: protocol, self.host, self.port)
        except OSError as err:
            raise SnmpError(f"Cannot reach {self.host}: {err}") from err
        try:
            for _attempt in range(self._retries + 1):
                protocol.request_id = secrets.randbelow(0x7FFFFFFE) + 1
                protocol.future = loop.create_future()
                transport.sendto(
                    encode_message(
                        version=self.version,
                        community=self.community,
                        pdu_type=pdu_type,
                        request_id=protocol.request_id,
                        varbinds=[(oid, None) for oid in oids],
                    )
                )
                try:
                    async with asyncio.timeout(self._timeout):
                        return await protocol.future
                except TimeoutError:
                    continue
            raise SnmpTimeoutError(f"No SNMP response from {self.host}")
        finally:
            transport.close()

    async def get(self, oids: Sequence[str]) -> dict[str, Any]:
        """Read the given OIDs. Missing objects map to a NoValue member."""
        if not oids:
            return {}
        message = await self._exchange(PDU_GET, oids)
        if message.error_status == _ERROR_NO_SUCH_NAME and len(oids) > 1:
            # SNMPv1 rejects the whole request when one OID does not exist.
            result: dict[str, Any] = {}
            for oid in oids:
                result.update(await self.get([oid]))
            return result
        if message.error_status == _ERROR_NO_SUCH_NAME:
            return {oids[0]: NoValue.NO_SUCH_OBJECT}
        if message.error_status:
            raise SnmpError(
                f"SNMP error status {message.error_status} (index {message.error_index})"
            )
        return dict(message.varbinds)

    async def walk(self, root: str, max_rows: int = 256) -> list[tuple[str, Any]]:
        """Read every object below ``root`` with GETNEXT requests."""
        rows: list[tuple[str, Any]] = []
        current = root
        while len(rows) < max_rows:
            message = await self._exchange(PDU_GET_NEXT, [current])
            if message.error_status or not message.varbinds:
                break
            oid, value = message.varbinds[0]
            if isinstance(value, NoValue) or not oid_in_subtree(oid, root) or oid == current:
                break
            rows.append((oid, value))
            current = oid
        return rows
