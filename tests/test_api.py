"""Tests for the CP750 ASCII protocol client."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from custom_components.dolby_cp750 import api
from custom_components.dolby_cp750.api import (
    Cp750Client,
    Cp750ConnectionError,
    Cp750TimeoutError,
    parse_line,
)

from .fakes import SERIAL, VERSION, FakeCp750


def _client(unit: FakeCp750, **kwargs: Any) -> Cp750Client:
    return Cp750Client(
        "192.0.2.10",
        connect_timeout=kwargs.pop("connect_timeout", 0.2),
        response_timeout=kwargs.pop("response_timeout", 0.05),
        connection_factory=unit.open_connection,  # type: ignore[arg-type]
        **kwargs,
    )


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (b"cp750.sys.fader 70\r\n", ("cp750.sys.fader", "70")),
        (b"CP750.SYS.INPUT_MODE dig_2\x00\r\n", ("cp750.sys.input_mode", "dig_2")),
        (b"cp750.sys.fader : 70\r\n", ("cp750.sys.fader", "70")),
        (
            b"  cp750.sys.ip_setting 10.0.0.2 255.0.0.0  \n",
            ("cp750.sys.ip_setting", "10.0.0.2 255.0.0.0"),
        ),
        (b"cp750.sys.time\r\n", ("cp750.sys.time", "")),
        (b"\r\n", None),
        (b"\x00\x00\r\n", None),
    ],
)
def test_parse_line(raw: bytes, expected: tuple[str, str] | None) -> None:
    """Both reply formats are parsed; empty lines are skipped."""
    assert parse_line(raw) == expected


def test_parse_line_without_key() -> None:
    """A line that starts with a colon has no parameter name."""
    assert parse_line(b": 70\r\n") is None


async def test_query_and_set() -> None:
    """Values are read and set over one connection."""
    unit = FakeCp750()
    client = _client(unit)

    assert await client.query("cp750.sys.fader") == "70"
    assert await client.set("cp750.sys.fader", 55) == "55"
    assert unit.value("cp750.sys.fader") == "55"
    assert await client.set("cp750.sys.input_mode", "dig_3") == "dig_3"
    assert unit.connections == 1
    assert client.connected
    assert unit.received == [
        "cp750.sys.fader ?",
        "cp750.sys.fader 55",
        "cp750.sys.input_mode dig_3",
    ]


async def test_invalid_value_returns_current_value() -> None:
    """The unit ignores a value it does not accept and reports the current one."""
    unit = FakeCp750()
    client = _client(unit)

    assert await client.set("cp750.sys.fader", 250) == "70"


@pytest.mark.parametrize("value", ["", "two words", "?", "line\nbreak", "fadér"])
async def test_set_rejects_unsafe_values(value: str) -> None:
    """Values that would break the line protocol are refused before sending."""
    unit = FakeCp750()
    with pytest.raises(ValueError):
        await _client(unit).set("cp750.sys.fader", value)
    assert unit.received == []


async def test_identify() -> None:
    """Version and serial number are read."""
    identity = await _client(FakeCp750()).identify()

    assert identity.version == VERSION
    assert identity.serial == SERIAL


async def test_identify_without_serial() -> None:
    """Firmware that does not know the serial number parameter still identifies."""
    unit = FakeCp750()
    unit.remove("cp750.sys.serial_number")

    identity = await _client(unit).identify()
    assert identity.version == VERSION
    assert identity.serial is None


async def test_identify_empty_version() -> None:
    """An empty version is not a CP750 answer."""
    unit = FakeCp750()
    unit.set_value("cp750.sysinfo.version", "")

    with pytest.raises(Cp750TimeoutError):
        await _client(unit).identify()


async def test_unknown_parameter_times_out_but_keeps_connection() -> None:
    """An unknown parameter gets an empty line, so the request times out."""
    unit = FakeCp750()
    client = _client(unit)

    with pytest.raises(Cp750TimeoutError):
        await client.query("cp750.sys.does_not_exist")
    assert client.connected
    assert await client.query("cp750.sys.mute") == "0"
    assert unit.connections == 1


async def test_unexpected_lines_are_skipped() -> None:
    """Lines for other parameters or warnings do not get mixed up with the reply."""
    unit = FakeCp750()
    client = _client(unit)
    await client.connect()
    unit.writers[0].send("Warning: oldest session closed\r\ncp750.sys.mute 1\r\n\r\n")

    assert await client.query("cp750.sys.fader") == "70"


async def test_connect_refused() -> None:
    """A unit that is switched off raises a connection error."""
    unit = FakeCp750()
    unit.online = False

    with pytest.raises(Cp750ConnectionError, match="Cannot connect"):
        await _client(unit).query("cp750.sys.fader")


async def test_connect_timeout() -> None:
    """A connect that hangs raises a connection error."""

    async def _slow(host: str, port: int) -> Any:
        await asyncio.sleep(1)

    client = Cp750Client("192.0.2.10", connect_timeout=0.01, connection_factory=_slow)
    with pytest.raises(Cp750ConnectionError, match="Timeout"):
        await client.connect()


async def test_unit_stops_answering() -> None:
    """A unit that accepts data but never answers raises a timeout error."""
    unit = FakeCp750()
    unit.hang = True

    with pytest.raises(Cp750TimeoutError):
        await _client(unit).query("cp750.sys.fader")


async def test_connection_closed_by_unit_reconnects() -> None:
    """A connection the unit closed is replaced transparently, once."""
    unit = FakeCp750()
    client = _client(unit)
    assert await client.query("cp750.sys.fader") == "70"

    unit.drop_connections()
    assert await client.query("cp750.sys.fader") == "70"
    assert unit.connections == 2
    assert client.connection_count == 2


async def test_connection_closed_and_unit_gone() -> None:
    """When the reconnect fails as well, the error is raised."""
    unit = FakeCp750()
    client = _client(unit)
    await client.connect()
    unit.drop_connections()
    unit.online = False

    with pytest.raises(Cp750ConnectionError, match="Cannot connect"):
        await client.query("cp750.sys.fader")
    assert not client.connected


async def test_fresh_connection_closed_is_not_retried() -> None:
    """A connection that closes right after it was opened is not retried."""
    unit = FakeCp750()
    original = unit.handle

    def _close_immediately(writer, line: str) -> None:
        unit.received.append(line)
        writer.remote_close()

    unit.handle = _close_immediately  # type: ignore[method-assign]
    with pytest.raises(Cp750ConnectionError, match="closed the connection"):
        await _client(unit).query("cp750.sys.fader")
    assert unit.connections == 1
    unit.handle = original  # type: ignore[method-assign]


async def test_write_error() -> None:
    """A failing write raises a connection error and closes the connection."""
    unit = FakeCp750()
    client = _client(unit)
    await client.connect()
    unit.fail_writes = True

    with pytest.raises(Cp750ConnectionError, match="lost"):
        await client.query("cp750.sys.fader")
    assert not client.connected
    # One reconnect was tried.
    assert unit.connections == 2


async def test_read_error_reconnects() -> None:
    """A broken stream is replaced by a new connection."""
    unit = FakeCp750()
    client = _client(unit)
    await client.connect()
    assert client._reader is not None
    client._reader.set_exception(ConnectionResetError("reset"))

    assert await client.query("cp750.sys.fader") == "70"
    assert unit.connections == 2


async def test_not_connected_guards() -> None:
    """The low-level helpers refuse to work without a connection."""
    client = _client(FakeCp750())
    with pytest.raises(Cp750ConnectionError):
        await client._write("cp750.sys.fader ?")
    with pytest.raises(Cp750ConnectionError):
        await client._readline(0.01)


async def test_send_raw_status() -> None:
    """A raw command returns all reply lines without blanks and NUL bytes."""
    unit = FakeCp750()
    lines = await _client(unit).send_raw("status")

    assert "cp750.sys.fader : 70" in lines
    assert "" not in lines
    assert len(lines) == len(unit.params)


async def test_send_raw_single_reply() -> None:
    """A query sent as raw command returns its reply line."""
    assert await _client(FakeCp750()).send_raw("cp750.sys.mute ?") == ["cp750.sys.mute 0"]


async def test_send_raw_exit_returns_what_arrived() -> None:
    """Exit closes the connection; that is not an error for a raw command."""
    unit = FakeCp750()
    client = _client(unit)

    assert await client.send_raw("exit") == []
    assert not client.connected


async def test_send_raw_stops_at_total_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    """A unit that keeps talking is cut off at the total timeout."""
    monkeypatch.setattr(api, "RAW_TOTAL_TIMEOUT", 0.0)
    assert await _client(FakeCp750()).send_raw("status") == []


@pytest.mark.parametrize("command", ["", "status\nexit", "fadér ?"])
async def test_send_raw_rejects_unsafe_commands(command: str) -> None:
    """Raw commands are one line of printable ASCII."""
    with pytest.raises(ValueError):
        await _client(FakeCp750()).send_raw(command)


async def test_disconnect_sends_exit() -> None:
    """Disconnect says goodbye so the unit frees the session right away."""
    unit = FakeCp750()
    client = _client(unit)
    await client.query("cp750.sys.fader")

    await client.disconnect()
    assert unit.received[-1] == "exit"
    assert not client.connected
    # A second disconnect is harmless.
    await client.disconnect()


async def test_disconnect_with_broken_connection() -> None:
    """Disconnect still closes when the goodbye cannot be sent."""
    unit = FakeCp750()
    client = _client(unit)
    await client.connect()
    unit.fail_writes = True

    await client.disconnect()
    assert not client.connected


async def test_disconnect_after_unit_closed() -> None:
    """Disconnect does not write to a connection that is already closing."""
    unit = FakeCp750()
    client = _client(unit)
    await client.connect()
    unit.writers[0].close()

    await client.disconnect()
    assert "exit" not in unit.received


async def test_close_tolerates_wait_closed_errors() -> None:
    """Errors while closing the transport are not raised."""
    unit = FakeCp750()
    client = _client(unit)
    await client.connect()

    async def _broken() -> None:
        raise ConnectionResetError("reset")

    unit.writers[0].wait_closed = _broken  # type: ignore[method-assign]
    await client.disconnect()
    assert not client.connected


async def test_send_raw_connection_closed_before_reply() -> None:
    """A connection that closes before any reply line is an error."""
    unit = FakeCp750()
    client = _client(unit)
    await client.connect()
    unit.drop_connections()
    unit.online = False

    with pytest.raises(Cp750ConnectionError):
        await client.send_raw("status")
