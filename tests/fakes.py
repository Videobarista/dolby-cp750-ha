"""In-memory stand-ins for a CP750 and its SNMP agent.

They speak the real protocols (ASCII lines and SNMP BER), but never open a
socket: the clients get them injected through their connection and endpoint
factories.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

from custom_components.dolby_cp750 import snmp

VERSION = "1.2.8.3"
SERIAL = "123456"

DECODE = ("4_discrete_sur", "auto", "lr_discrete", "prologic", "prologic_2", "surround_ex")
INPUT_MODES = ("analog", "dig_1", "dig_2", "dig_3", "dig_4", "mic", "non_sync")


def _range(low: int, high: int) -> Callable[[str], bool]:
    def _check(value: str) -> bool:
        return value.lstrip("-").isdigit() and low <= int(value) <= high

    return _check


def _one_of(*choices: str) -> Callable[[str], bool]:
    return lambda value: value in choices


def default_parameters() -> dict[str, tuple[str, Callable[[str], bool]]]:
    """Return the parameters of table 7-1 with a value and a validator."""
    params: dict[str, tuple[str, Callable[[str], bool]]] = {
        "cp750.sysinfo.version": (VERSION, lambda _: False),
        "cp750.sys.serial_number": (SERIAL, lambda _: False),
        "cp750.sys.fader": ("70", _range(0, 100)),
        "cp750.sys.mute": ("0", _range(0, 1)),
        "cp750.sys.input_mode": ("dig_1", _one_of(*INPUT_MODES, "last")),
        "cp750.sys.power_on_input": ("last", _one_of(*INPUT_MODES, "last")),
        "cp750.sys.non_sync_format": ("60", _one_of("60", "61", "70", "71", "73", "74", "75")),
        "cp750.sys.surround_delay": ("20", _range(0, 150)),
    }
    for suffix in ("1", "2", "3", "4", "a"):
        params[f"cp750.sys.pcm_2_channel_decode_mode_{suffix}"] = ("lr_discrete", _one_of(*DECODE))
    for suffix in ("1", "2", "3", "4"):
        key = f"cp750.sys.dolby_digital_2_channel_decode_mode_{suffix}"
        params[key] = ("n_a", _one_of(*DECODE))
    for suffix in ("1", "2", "3", "4", "a", "m", "n"):
        params[f"cp750.sys.fader_preset_{suffix}"] = ("70", _range(0, 100))
        params[f"cp750.sys.fader_preset_{suffix}_enable"] = ("0", _range(0, 1))
    for source in INPUT_MODES:
        params[f"cp750.sys.{source}_global_delay"] = ("0", _range(0, 170))
    return params


class FakeWriter:
    """Receives command lines and feeds the replies to the paired reader."""

    def __init__(self, unit: FakeCp750, reader: asyncio.StreamReader) -> None:
        self._unit = unit
        self._reader = reader
        self._buffer = b""
        self._closing = False
        self._remote_closed = False

    def write(self, data: bytes) -> None:
        if self._closing or self._remote_closed:
            return
        self._buffer += data
        while b"\n" in self._buffer:
            line, _, self._buffer = self._buffer.partition(b"\n")
            self._unit.handle(self, line.decode("ascii"))

    async def drain(self) -> None:
        if self._unit.fail_writes:
            raise ConnectionResetError("Connection reset by peer")

    def is_closing(self) -> bool:
        return self._closing

    def close(self) -> None:
        self._closing = True
        if not self._reader.at_eof():
            self._reader.feed_eof()

    async def wait_closed(self) -> None:
        return None

    def remote_close(self) -> None:
        """The unit closes the connection; the client notices on its next read."""
        self._remote_closed = True
        if not self._reader.at_eof():
            self._reader.feed_eof()

    def send(self, text: str) -> None:
        """Send raw text to the client."""
        if not self._closing and not self._remote_closed and not self._reader.at_eof():
            self._reader.feed_data(text.encode("ascii"))


class FakeCp750:
    """A CP750 that follows the behaviour described in the manual."""

    def __init__(self) -> None:
        self.params = default_parameters()
        self.online = True
        self.hang = False
        self.fail_writes = False
        self.received: list[str] = []
        self.connections = 0
        self.writers: list[FakeWriter] = []
        self.last_input = "dig_1"

    def value(self, key: str) -> str:
        return self.params[key][0]

    def set_value(self, key: str, value: str) -> None:
        self.params[key] = (value, self.params[key][1])

    def remove(self, key: str) -> None:
        """Make the unit not know a parameter (older firmware)."""
        del self.params[key]

    async def open_connection(
        self, host: str, port: int
    ) -> tuple[asyncio.StreamReader, FakeWriter]:
        if not self.online:
            raise OSError(113, "No route to host")
        reader = asyncio.StreamReader()
        writer = FakeWriter(self, reader)
        self.connections += 1
        self.writers.append(writer)
        return reader, writer

    def drop_connections(self) -> None:
        """Close every connection from the unit's side."""
        for writer in self.writers:
            writer.remote_close()
        self.writers.clear()

    def handle(self, writer: FakeWriter, line: str) -> None:
        self.received.append(line)
        if self.hang:
            return
        text = line.strip()
        if not text:
            writer.send("\r\n")
            return
        key, _, argument = text.partition(" ")
        key = key.lower()
        argument = argument.strip()

        if key == "exit":
            writer.close()
            return
        if key == "status":
            for name, (value, _check) in self.params.items():
                writer.send(f"{name} : {value}\r\n")
            writer.send("\r\n")
            return
        if key == "help":
            writer.send("help\r\nstatus\r\nexit\r\n\r\n")
            return
        if key not in self.params:
            writer.send("\r\n")
            return

        value, check = self.params[key]
        if argument != "?":
            if key == "cp750.sys.input_mode" and argument == "last":
                self.last_input, value = value, self.last_input
                self.set_value(key, value)
            elif check(argument):
                if key == "cp750.sys.input_mode":
                    self.last_input = value
                value = argument
                self.set_value(key, value)
        # Real units pad some replies with NUL bytes.
        writer.send(f"{key} {value}\x00\r\n\r\n")


def _oid_key(oid: str) -> tuple[int, ...]:
    return tuple(int(part) for part in oid.split("."))


class FakeSnmpAgent:
    """An SNMP agent with a fixed set of objects."""

    def __init__(self, objects: dict[str, Any], community: str = "public") -> None:
        self.objects = dict(objects)
        self.community = community
        self.versions = {snmp.SNMP_V1, snmp.SNMP_V2C}
        self.online = True
        self.requests: list[snmp.SnmpMessage] = []

    async def __call__(
        self,
        loop: asyncio.AbstractEventLoop,
        factory: Callable[[], asyncio.DatagramProtocol],
        host: str,
        port: int,
    ) -> FakeTransport:
        return FakeTransport(self, loop, factory())

    def respond(self, data: bytes) -> bytes | None:
        request = snmp.decode_message(data)
        self.requests.append(request)
        if (
            not self.online
            or request.version not in self.versions
            or request.community != self.community
        ):
            return None
        varbinds: list[tuple[str, Any]] = []
        error_status = 0
        error_index = 0
        for index, (oid, _value) in enumerate(request.varbinds, start=1):
            if request.pdu_type == snmp.PDU_GET_NEXT:
                following = sorted(
                    (key for key in self.objects if _oid_key(key) > _oid_key(oid)), key=_oid_key
                )
                if following:
                    varbinds.append((following[0], self.objects[following[0]]))
                elif request.version == snmp.SNMP_V1:
                    error_status, error_index = 2, index
                    varbinds.append((oid, None))
                else:
                    varbinds.append((oid, snmp.NoValue.END_OF_MIB_VIEW))
            elif oid in self.objects:
                varbinds.append((oid, self.objects[oid]))
            elif request.version == snmp.SNMP_V1:
                error_status, error_index = 2, index
                varbinds.append((oid, None))
            else:
                varbinds.append((oid, snmp.NoValue.NO_SUCH_OBJECT))
        if error_status:
            varbinds = [(oid, None) for oid, _value in request.varbinds]
        return snmp.encode_message(
            version=request.version,
            community=request.community,
            pdu_type=snmp.PDU_RESPONSE,
            request_id=request.request_id,
            varbinds=varbinds,
            error_status=error_status,
            error_index=error_index,
        )


class FakeTransport:
    """Datagram transport that hands requests to a FakeSnmpAgent."""

    def __init__(
        self,
        agent: FakeSnmpAgent,
        loop: asyncio.AbstractEventLoop,
        protocol: asyncio.DatagramProtocol,
    ) -> None:
        self._agent = agent
        self._loop = loop
        self._protocol = protocol
        self.closed = False

    def sendto(self, data: bytes) -> None:
        reply = self._agent.respond(data)
        if reply is not None:
            self._loop.call_soon(self._protocol.datagram_received, reply, ("192.0.2.10", 161))

    def close(self) -> None:
        self.closed = True
