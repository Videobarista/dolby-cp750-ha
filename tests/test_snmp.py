"""Tests for the minimal SNMP client."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from custom_components.dolby_cp750 import snmp
from custom_components.dolby_cp750.snmp import (
    SNMP_V1,
    SNMP_V2C,
    NoValue,
    SnmpClient,
    SnmpError,
    SnmpTimeoutError,
    TimeTicks,
)

from .fakes import FakeSnmpAgent

SYS_DESCR = "1.3.6.1.2.1.1.1.0"
ROOT = "1.3.6.1.4.1.6729.2.1.1.1.2"

# SNMPv1 GetRequest, community "public", request ID 1, for sysDescr.0, as sent by
# net-snmp's snmpget.
GET_SYS_DESCR_V1 = bytes.fromhex(
    "302602010004067075626c6963a019020101020100020100300e300c06082b060102010101000500"
)

OBJECTS: dict[str, Any] = {
    SYS_DESCR: b"Dolby CP750",
    f"{ROOT}.2.6.0": 70,
    f"{ROOT}.2.5.0": b"dig_1",
    f"{ROOT}.2.11.0": b"10 55 00 60 10 01 47 48",
    "1.3.6.1.2.1.1.3.0": TimeTicks(4_294_967_295),
}


def _client(agent: Any, version: int = SNMP_V2C, **kwargs: Any) -> SnmpClient:
    return SnmpClient(
        "192.0.2.10",
        "public",
        version=version,
        timeout=kwargs.pop("timeout", 0.05),
        retries=kwargs.pop("retries", 0),
        endpoint_factory=agent,
    )


def test_encode_matches_reference_packet() -> None:
    """The encoder produces the same bytes as net-snmp."""
    message = snmp.encode_message(
        version=SNMP_V1,
        community="public",
        pdu_type=snmp.PDU_GET,
        request_id=1,
        varbinds=[(SYS_DESCR, None)],
    )
    assert message == GET_SYS_DESCR_V1


def test_decode_reference_packet() -> None:
    """The decoder reads the reference packet back."""
    message = snmp.decode_message(GET_SYS_DESCR_V1)
    assert message.version == SNMP_V1
    assert message.community == "public"
    assert message.pdu_type == snmp.PDU_GET
    assert message.request_id == 1
    assert message.varbinds == [(SYS_DESCR, None)]


@pytest.mark.parametrize(
    "value",
    [
        0,
        127,
        128,
        65_535,
        2**31 - 1,
        "dig_1",
        b"\x00\xff",
        None,
        TimeTicks(0),
        TimeTicks(4_294_967_295),
        NoValue.NO_SUCH_OBJECT,
        NoValue.NO_SUCH_INSTANCE,
        NoValue.END_OF_MIB_VIEW,
    ],
)
def test_value_round_trip(value: Any) -> None:
    """Values survive encoding and decoding."""
    data = snmp.encode_message(
        version=SNMP_V2C,
        community="public",
        pdu_type=snmp.PDU_RESPONSE,
        request_id=12345,
        varbinds=[(f"{ROOT}.2.6.0", value)],
    )
    decoded = snmp.decode_message(data).varbinds[0][1]
    expected = value.encode() if isinstance(value, str) else value
    assert decoded == expected


def test_long_lengths_round_trip() -> None:
    """Long-form lengths (more than 127 bytes) are encoded and decoded."""
    community = "c" * 300
    data = snmp.encode_message(
        version=SNMP_V2C,
        community=community,
        pdu_type=snmp.PDU_GET,
        request_id=7,
        varbinds=[(SYS_DESCR, None)],
    )
    assert snmp.decode_message(data).community == community


@pytest.mark.parametrize(
    "oid", ["1.3.6.1.4.1.6729.2.1.1.1.2.2.11.0", "2.999.3", "0.39", "1.3.6.1.4.1.4294967295"]
)
def test_oid_round_trip(oid: str) -> None:
    """OIDs, including large arcs and the 2.x branch, survive a round trip."""
    encoded = snmp.encode_oid(oid)
    assert snmp.decode_oid(encoded[2:]) == oid


@pytest.mark.parametrize("oid", ["", "1", "3.1", "1.40", "1.3.x", "1.3.-1"])
def test_invalid_oid(oid: str) -> None:
    """Malformed OIDs are rejected."""
    with pytest.raises(ValueError):
        snmp.encode_oid(oid)


@pytest.mark.parametrize("body", [b"", b"\x2b\x86"])
def test_invalid_oid_body(body: bytes) -> None:
    """Empty or truncated OID content is rejected."""
    with pytest.raises(SnmpError):
        snmp.decode_oid(body)


def test_encode_unsupported_value() -> None:
    """Values without an SNMP type are refused."""
    for value in (True, 1.5):
        with pytest.raises(TypeError):
            snmp.encode_message(
                version=SNMP_V2C,
                community="public",
                pdu_type=snmp.PDU_GET,
                request_id=1,
                varbinds=[(SYS_DESCR, value)],
            )


@pytest.mark.parametrize(
    "data",
    [
        b"",
        b"\x30",
        b"\x30\x05\x02\x01",
        b"\x02\x01\x00",
        b"\x30\x85\x00\x00\x00\x00\x01",
        bytes.fromhex("3006020100040000"),
    ],
)
def test_decode_garbage(data: bytes) -> None:
    """Truncated or malformed messages raise SnmpError."""
    with pytest.raises(SnmpError):
        snmp.decode_message(data)


def test_decode_unknown_pdu_and_value_types() -> None:
    """Unknown PDU or value types raise SnmpError."""
    trap = bytearray(GET_SYS_DESCR_V1)
    trap[13] = 0xA4
    with pytest.raises(SnmpError, match="PDU type"):
        snmp.decode_message(bytes(trap))

    odd_value = bytearray(GET_SYS_DESCR_V1)
    odd_value[-2] = 0x47
    with pytest.raises(SnmpError, match="value type"):
        snmp.decode_message(bytes(odd_value))


def test_decode_other_value_types() -> None:
    """IP addresses, counters and opaque values are decoded."""
    assert snmp._decode_value(0x40, bytes([192, 0, 2, 10])) == "192.0.2.10"
    assert snmp._decode_value(0x41, b"\x01\x00") == 256
    assert snmp._decode_value(0x46, b"\xff" * 8) == 2**64 - 1
    assert snmp._decode_value(0x44, b"\x01") == b"\x01"
    assert snmp._decode_value(0x02, b"") == 0
    assert snmp._decode_value(0x02, b"\xff") == -1
    assert snmp._decode_value(0x06, b"\x2b\x06") == "1.3.6"


def test_helpers() -> None:
    """Text conversion and subtree checks."""
    assert snmp.as_text(b" dig_1\x00 ") == "dig_1"
    assert snmp.as_text(" PCM ") == "PCM"
    assert snmp.as_text(5) is None
    assert snmp.oid_in_subtree(f"{ROOT}.2.6.0", ROOT)
    assert not snmp.oid_in_subtree(f"{ROOT}0.1", ROOT)
    assert not snmp.oid_in_subtree(ROOT, ROOT)


async def test_get_v2c() -> None:
    """A v2c GET returns values and marks missing objects."""
    agent = FakeSnmpAgent(OBJECTS)
    result = await _client(agent).get([SYS_DESCR, f"{ROOT}.2.6.0", f"{ROOT}.2.99.0"])

    assert result == {
        SYS_DESCR: b"Dolby CP750",
        f"{ROOT}.2.6.0": 70,
        f"{ROOT}.2.99.0": NoValue.NO_SUCH_OBJECT,
    }
    assert len(agent.requests) == 1


async def test_get_nothing() -> None:
    """Asking for no OIDs sends nothing."""
    agent = FakeSnmpAgent(OBJECTS)
    assert await _client(agent).get([]) == {}
    assert agent.requests == []


async def test_get_v1_falls_back_to_single_requests() -> None:
    """SNMPv1 fails a whole request for one missing OID; ask one by one then."""
    agent = FakeSnmpAgent(OBJECTS)
    result = await _client(agent, SNMP_V1).get([SYS_DESCR, f"{ROOT}.2.99.0"])

    assert result == {SYS_DESCR: b"Dolby CP750", f"{ROOT}.2.99.0": NoValue.NO_SUCH_OBJECT}
    assert len(agent.requests) == 3


async def test_get_error_status() -> None:
    """Other error statuses raise SnmpError."""
    agent = FakeSnmpAgent(OBJECTS)

    def _gen_err(data: bytes) -> bytes:
        request = snmp.decode_message(data)
        return snmp.encode_message(
            version=request.version,
            community=request.community,
            pdu_type=snmp.PDU_RESPONSE,
            request_id=request.request_id,
            varbinds=request.varbinds,
            error_status=5,
            error_index=1,
        )

    agent.respond = _gen_err  # type: ignore[method-assign]
    with pytest.raises(SnmpError, match="error status 5"):
        await _client(agent).get([SYS_DESCR])


async def test_get_timeout_with_retries() -> None:
    """No answer: the request is retried, then a timeout is raised."""
    agent = FakeSnmpAgent(OBJECTS)
    agent.online = False

    with pytest.raises(SnmpTimeoutError):
        await _client(agent, retries=2, timeout=0.01).get([SYS_DESCR])
    assert len(agent.requests) == 3


async def test_wrong_community_is_silent() -> None:
    """Agents ignore requests with a wrong community."""
    agent = FakeSnmpAgent(OBJECTS, community="secret")
    with pytest.raises(SnmpTimeoutError):
        await _client(agent).get([SYS_DESCR])


async def test_endpoint_error() -> None:
    """A failure to open the UDP socket raises SnmpError."""

    async def _broken(*_args: Any) -> Any:
        raise OSError("no route")

    with pytest.raises(SnmpError, match="Cannot reach"):
        await _client(_broken).get([SYS_DESCR])


class _ScriptedTransport:
    """Transport that runs a callback for each datagram sent."""

    def __init__(self, loop: asyncio.AbstractEventLoop, protocol: Any, script: Any) -> None:
        self._loop = loop
        self._protocol = protocol
        self._script = script
        self.closed = False

    def sendto(self, data: bytes) -> None:
        self._loop.call_soon(self._script, self._protocol, data)

    def close(self) -> None:
        self.closed = True


def _scripted(script: Any) -> Any:
    async def _factory(loop: asyncio.AbstractEventLoop, factory: Any, host: str, port: int) -> Any:
        return _ScriptedTransport(loop, factory(), script)

    return _factory


def _reply_to(data: bytes, request_id: int | None = None) -> bytes:
    request = snmp.decode_message(data)
    return snmp.encode_message(
        version=request.version,
        community=request.community,
        pdu_type=snmp.PDU_RESPONSE,
        request_id=request.request_id if request_id is None else request_id,
        varbinds=[(SYS_DESCR, b"Dolby CP750")],
    )


async def test_network_error() -> None:
    """An ICMP error reported by the transport raises SnmpError."""

    def _script(protocol: Any, data: bytes) -> None:
        protocol.error_received(OSError("port unreachable"))

    with pytest.raises(SnmpError, match="Network error"):
        await _client(_scripted(_script)).get([SYS_DESCR])


async def test_foreign_and_garbage_datagrams_are_ignored() -> None:
    """Garbage and replies to other requests are skipped; the real reply counts."""

    def _script(protocol: Any, data: bytes) -> None:
        protocol.datagram_received(b"garbage", ("192.0.2.10", 161))
        protocol.datagram_received(_reply_to(data, request_id=99), ("192.0.2.10", 161))
        protocol.datagram_received(data, ("192.0.2.10", 161))  # a GET, not a response
        protocol.datagram_received(_reply_to(data), ("192.0.2.10", 161))
        # Late extras after the answer are harmless.
        protocol.datagram_received(_reply_to(data), ("192.0.2.10", 161))
        protocol.error_received(OSError("late"))

    assert await _client(_scripted(_script)).get([SYS_DESCR]) == {SYS_DESCR: b"Dolby CP750"}


def test_protocol_without_request() -> None:
    """Datagrams and errors before a request are ignored."""
    protocol = snmp._SnmpProtocol()
    protocol.datagram_received(b"garbage", ("192.0.2.10", 161))
    protocol.error_received(OSError("nothing pending"))


async def test_walk_v2c() -> None:
    """A walk returns the subtree in order and stops at its end."""
    agent = FakeSnmpAgent(OBJECTS)
    rows = await _client(agent).walk(ROOT)

    assert [oid for oid, _value in rows] == [f"{ROOT}.2.5.0", f"{ROOT}.2.6.0", f"{ROOT}.2.11.0"]


async def test_walk_to_end_of_mib() -> None:
    """A walk past the last object stops at endOfMibView (v2c) or noSuchName (v1)."""
    for version in (SNMP_V2C, SNMP_V1):
        agent = FakeSnmpAgent(OBJECTS)
        rows = await _client(agent, version).walk("1.3.6.1.4.1")
        assert len(rows) == 3


async def test_walk_max_rows() -> None:
    """A walk stops at the row limit."""
    rows = await _client(FakeSnmpAgent(OBJECTS)).walk(ROOT, max_rows=2)
    assert len(rows) == 2


async def test_walk_stops_on_repeated_oid() -> None:
    """An agent that returns the same OID again does not make the walk loop."""

    def _script(protocol: Any, data: bytes) -> None:
        request = snmp.decode_message(data)
        protocol.datagram_received(
            snmp.encode_message(
                version=request.version,
                community=request.community,
                pdu_type=snmp.PDU_RESPONSE,
                request_id=request.request_id,
                varbinds=[(f"{ROOT}.2.6.0", 70)],
            ),
            ("192.0.2.10", 161),
        )

    rows = await _client(_scripted(_script)).walk(ROOT)
    assert rows == [(f"{ROOT}.2.6.0", 70)]
