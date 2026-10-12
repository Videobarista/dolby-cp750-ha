"""Client for the ASCII control protocol of the Dolby CP750.

The CP750 accepts plain text commands on TCP port 61408 (manual section 7.2):

* ``<parameter> <value>`` sets a value; the unit answers ``<parameter> <value>``
  with the value it now uses.
* ``<parameter> ?`` asks for a value; the unit answers the same way.
* An unknown value is ignored and the current value is returned; an unknown
  parameter returns an empty line. The unit never sends error messages.

The ``status`` command answers with ``<parameter> : <value>`` lines. Replies can
contain NUL bytes and are followed by an empty line. This client does not rely
on that framing: it reads lines until one carries the parameter it asked for.

The unit accepts 20 TCP sessions and drops the oldest one when a 21st connects,
so the client keeps one connection open and serialises all requests on it.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
import logging
import re

from .const import DEFAULT_PORT, KEY_SERIAL, KEY_VERSION

_LOGGER = logging.getLogger(__name__)

CONNECT_TIMEOUT = 3.0
RESPONSE_TIMEOUT = 2.0
RAW_IDLE_TIMEOUT = 0.5
RAW_TOTAL_TIMEOUT = 4.0
RAW_MAX_LINES = 2000

# Line ending for commands. A bare LF is what the open-source cp750-java library
# (used by the openHAB binding) sends to real units; leading and trailing white
# space is ignored by the CP750.
EOL = b"\n"

_LINE = re.compile(r"(?P<key>[^\s:]+)\s*:?\s*(?P<value>.*)")
_SAFE_VALUE = re.compile(r"[\x21-\x7e]+")

type ConnectionFactory = Callable[
    [str, int], Awaitable[tuple[asyncio.StreamReader, asyncio.StreamWriter]]
]


class Cp750Error(Exception):
    """Base error of the CP750 client."""


class Cp750ConnectionError(Cp750Error):
    """The unit cannot be reached or closed the connection."""


class Cp750TimeoutError(Cp750Error):
    """The unit is connected but did not answer a request in time."""


@dataclass(frozen=True, slots=True)
class Cp750Identity:
    """Identification of a unit."""

    version: str
    serial: str | None


def parse_line(raw: bytes) -> tuple[str, str] | None:
    """Split a reply line into a lower-case parameter name and its value.

    Handles both ``key value`` (normal replies) and ``key : value`` (output of
    the ``status`` command). Returns None for empty lines.
    """
    text = raw.decode("ascii", errors="replace").replace("\x00", "").strip()
    if not text:
        return None
    match = _LINE.fullmatch(text)
    if match is None:
        return None
    return match["key"].lower(), match["value"].strip()


async def _open_connection(
    host: str, port: int
) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
    """Open a TCP connection to the unit."""
    return await asyncio.open_connection(host, port)


class Cp750Client:
    """Persistent connection to one CP750."""

    def __init__(
        self,
        host: str,
        port: int = DEFAULT_PORT,
        *,
        connect_timeout: float = CONNECT_TIMEOUT,
        response_timeout: float = RESPONSE_TIMEOUT,
        connection_factory: ConnectionFactory | None = None,
    ) -> None:
        """Initialize the client; nothing is opened until the first request."""
        self.host = host
        self.port = port
        self._connect_timeout = connect_timeout
        self._response_timeout = response_timeout
        self._connection_factory = connection_factory or _open_connection
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._lock = asyncio.Lock()
        self.connection_count = 0

    @property
    def connected(self) -> bool:
        """Return True while a connection is open."""
        return self._writer is not None and not self._writer.is_closing()

    async def connect(self) -> None:
        """Open the connection if it is not open yet."""
        async with self._lock:
            await self._ensure_connected()

    async def _ensure_connected(self) -> None:
        """Open the connection if needed; the caller holds the lock."""
        if self.connected:
            return
        try:
            async with asyncio.timeout(self._connect_timeout):
                reader, writer = await self._connection_factory(self.host, self.port)
        except TimeoutError as err:
            raise Cp750ConnectionError(f"Timeout connecting to {self.host}:{self.port}") from err
        except OSError as err:
            raise Cp750ConnectionError(f"Cannot connect to {self.host}:{self.port}: {err}") from err
        self._reader = reader
        self._writer = writer
        self.connection_count += 1
        _LOGGER.debug("Connected to CP750 at %s:%s", self.host, self.port)

    async def disconnect(self) -> None:
        """Say goodbye to the unit and close the connection."""
        async with self._lock:
            writer = self._writer
            if writer is None:
                return
            if not writer.is_closing():
                try:
                    writer.write(b"exit" + EOL)
                    async with asyncio.timeout(1):
                        await writer.drain()
                except (OSError, TimeoutError) as err:
                    _LOGGER.debug("Could not send exit to %s: %s", self.host, err)
            await self._close()

    async def _close(self) -> None:
        """Close the connection without talking to the unit."""
        writer = self._writer
        self._reader = None
        self._writer = None
        if writer is None:
            return
        writer.close()
        try:
            async with asyncio.timeout(1):
                await writer.wait_closed()
        except (OSError, TimeoutError) as err:
            _LOGGER.debug("Error while closing the connection to %s: %s", self.host, err)

    async def query(self, key: str) -> str:
        """Ask the unit for the value of a parameter."""
        return await self._request(key, "?")

    async def set(self, key: str, value: str | int) -> str:
        """Set a parameter and return the value the unit reports back."""
        text = str(value)
        if not _SAFE_VALUE.fullmatch(text) or text == "?":
            raise ValueError(f"Invalid value for {key}: {text!r}")
        return await self._request(key, text)

    async def identify(self) -> Cp750Identity:
        """Read the firmware version and, if available, the serial number."""
        version = await self.query(KEY_VERSION)
        if not version:
            raise Cp750TimeoutError("The unit did not report a firmware version")
        try:
            serial: str | None = await self.query(KEY_SERIAL)
        except Cp750TimeoutError:
            serial = None
        return Cp750Identity(version=version, serial=serial or None)

    async def send_raw(self, command: str) -> list[str]:
        """Send a command line as-is and return the reply lines.

        Used for diagnostics and the ``send_command`` action. Lines are collected
        until the unit stays quiet for a moment, so multi-line replies such as
        ``status`` and ``help`` come back complete.
        """
        if not command or not all(" " <= char <= "~" for char in command):
            raise ValueError("A command is one line of printable ASCII text")
        expect_close = command.strip().lower() == "exit"

        async def _exchange() -> list[str]:
            await self._write(command)
            return await self._collect_lines(expect_close=expect_close)

        return await self._with_connection(_exchange)

    async def _request(self, key: str, argument: str) -> str:
        """Send ``key argument`` and return the value of the matching reply."""

        async def _exchange() -> str:
            await self._write(f"{key} {argument}")
            return await self._read_value(key.lower())

        return await self._with_connection(_exchange)

    async def _with_connection[T](self, exchange: Callable[[], Awaitable[T]]) -> T:
        """Run one exchange under the lock, reconnecting once if needed.

        The unit may have closed an open connection in the meantime (for
        example when a 21st client connected). That shows up as a closed
        connection on the next request; a fresh connection is tried once
        before the error is raised.
        """
        async with self._lock:
            reused = self.connected
            await self._ensure_connected()
            try:
                return await exchange()
            except Cp750ConnectionError as err:
                if not reused:
                    raise
                _LOGGER.debug("Connection to %s was closed (%s), reconnecting", self.host, err)
            await self._ensure_connected()
            return await exchange()

    async def _write(self, line: str) -> None:
        """Write one command line."""
        if self._writer is None:
            raise Cp750ConnectionError("Not connected")
        _LOGGER.debug("Sending to %s: %s", self.host, line)
        try:
            self._writer.write(line.encode("ascii") + EOL)
            await self._writer.drain()
        except OSError as err:
            await self._close()
            raise Cp750ConnectionError(f"Connection to {self.host} lost: {err}") from err

    async def _readline(self, timeout: float) -> bytes:
        """Read one raw line; raise Cp750TimeoutError when none arrives in time."""
        if self._reader is None:
            raise Cp750ConnectionError("Not connected")
        try:
            async with asyncio.timeout(timeout):
                raw = await self._reader.readline()
        except TimeoutError as err:
            raise Cp750TimeoutError(f"No answer from {self.host}") from err
        except (OSError, ValueError) as err:
            # ValueError: a line longer than the stream buffer limit.
            await self._close()
            raise Cp750ConnectionError(f"Connection to {self.host} lost: {err}") from err
        if not raw:
            await self._close()
            raise Cp750ConnectionError(f"{self.host} closed the connection")
        return raw

    async def _read_value(self, key: str) -> str:
        """Read lines until the reply for ``key`` arrives."""
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self._response_timeout
        while True:
            remaining = deadline - loop.time()
            if remaining <= 0:
                raise Cp750TimeoutError(f"No answer from {self.host} for {key}")
            raw = await self._readline(remaining)
            parsed = parse_line(raw)
            if parsed is None:
                continue
            reply_key, value = parsed
            if reply_key == key:
                _LOGGER.debug("Received from %s: %s %s", self.host, reply_key, value)
                return value
            _LOGGER.debug("Ignoring line from %s while waiting for %s: %r", self.host, key, raw)

    async def _collect_lines(self, *, expect_close: bool = False) -> list[str]:
        """Collect reply lines until the unit is quiet or the time is up."""
        loop = asyncio.get_running_loop()
        deadline = loop.time() + RAW_TOTAL_TIMEOUT
        lines: list[str] = []
        while len(lines) < RAW_MAX_LINES:
            remaining = deadline - loop.time()
            if remaining <= 0:
                break
            try:
                raw = await self._readline(min(RAW_IDLE_TIMEOUT, remaining))
            except Cp750TimeoutError:
                break
            except Cp750ConnectionError:
                # "exit" makes the unit close the connection; keep what arrived.
                if expect_close or lines:
                    break
                raise
            text = raw.decode("ascii", errors="replace").replace("\x00", "").strip()
            if text:
                lines.append(text)
        return lines
