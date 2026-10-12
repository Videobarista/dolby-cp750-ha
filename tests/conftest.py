"""Fixtures for the Dolby CP750 tests."""

from __future__ import annotations

from collections.abc import Generator
from typing import Any
from unittest.mock import AsyncMock, PropertyMock, patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.dolby_cp750 import api, snmp
from custom_components.dolby_cp750.api import Cp750Client
from custom_components.dolby_cp750.const import (
    CONF_SERIAL,
    CONF_SNMP_COMMUNITY,
    CONF_SNMP_ENABLED,
    CONF_SNMP_VERSION,
    DEFAULT_PORT,
    DOMAIN,
    OID_BITSTREAM_FORMAT,
    OID_DECODE_MODE,
    OID_DIGITAL_VALID,
    OID_FADER_LEVEL,
    OID_INPUT_SELECTION,
    OID_METER_LEVELS,
    OID_MUTE_STATUS,
    OID_RELAY_STATUS,
    OID_SERIAL,
    OID_SYS_DESCR,
    OID_SYS_UPTIME,
)
from custom_components.dolby_cp750.snmp import SNMP_V2C, SnmpClient, TimeTicks
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant

from .fakes import SERIAL, FakeCp750, FakeSnmpAgent

# Documentation address (RFC 5737); the fakes never open a socket.
HOST = "192.0.2.10"

ENTRY_DATA: dict[str, Any] = {
    CONF_HOST: HOST,
    CONF_PORT: DEFAULT_PORT,
    CONF_SERIAL: SERIAL,
    CONF_SNMP_ENABLED: True,
    CONF_SNMP_COMMUNITY: "public",
    CONF_SNMP_VERSION: "2c",
}

SNMP_OBJECTS: dict[str, Any] = {
    OID_SYS_DESCR: b"Dolby CP750",
    OID_SYS_UPTIME: TimeTicks(360_000),  # one hour
    OID_SERIAL: int(SERIAL),
    OID_DIGITAL_VALID[1]: 1,
    OID_DIGITAL_VALID[2]: 0,
    OID_DIGITAL_VALID[3]: 2,
    OID_DIGITAL_VALID[4]: 0,
    OID_INPUT_SELECTION: b"dig_1",
    OID_FADER_LEVEL: 70,
    OID_BITSTREAM_FORMAT: b"PCM\x00",
    OID_DECODE_MODE: b"lr_discrete",
    OID_MUTE_STATUS: 1,
    OID_RELAY_STATUS: 1,
    OID_METER_LEVELS: b"10 55 00 60 10 01 47 48",
}


@pytest.fixture
def no_real_connections() -> Generator[None]:
    """Make sure the clients never open a real socket.

    Clients that are not wired to a fake (for example an entry that Home
    Assistant reloads while the test shuts down) see an unreachable unit.
    """

    async def _no_tcp(host: str, port: int) -> Any:
        raise OSError(f"No real connections in tests ({host}:{port})")

    async def _no_udp(*_args: Any) -> Any:
        raise OSError("No real SNMP in tests")

    with (
        patch.object(api, "_open_connection", _no_tcp),
        patch.object(snmp, "_create_endpoint", _no_udp),
    ):
        yield


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(
    no_real_connections: None, enable_custom_integrations: None
) -> None:
    """Let Home Assistant load the integration from custom_components.

    ``no_real_connections`` comes first, so it is still active while the
    ``hass`` fixture shuts down.
    """


@pytest.fixture(autouse=True)
def short_raw_timeouts() -> Generator[None]:
    """Make raw commands (status, send_command) finish quickly."""
    with patch.object(api, "RAW_IDLE_TIMEOUT", 0.05):
        yield


@pytest.fixture
def entity_registry_enabled_by_default() -> Generator[None]:
    """Enable entities that are disabled by default."""
    with patch(
        "homeassistant.helpers.entity.Entity.entity_registry_enabled_default",
        return_value=True,
        new_callable=PropertyMock,
    ):
        yield


@pytest.fixture
def fake_unit() -> Generator[FakeCp750]:
    """Patch the CP750 client so it talks to an in-memory unit."""
    unit = FakeCp750()

    def _client(host: str, port: int = DEFAULT_PORT, **_kwargs: Any) -> Cp750Client:
        return Cp750Client(
            host,
            port,
            connect_timeout=0.2,
            response_timeout=0.05,
            connection_factory=unit.open_connection,  # type: ignore[arg-type]
        )

    with (
        patch("custom_components.dolby_cp750.Cp750Client", side_effect=_client),
        patch("custom_components.dolby_cp750.config_flow.Cp750Client", side_effect=_client),
    ):
        yield unit


@pytest.fixture
def fake_agent() -> Generator[FakeSnmpAgent]:
    """Patch the SNMP client so it talks to an in-memory agent."""
    agent = FakeSnmpAgent(SNMP_OBJECTS)

    def _client(
        host: str, community: str, *, version: int = SNMP_V2C, port: int = 161, **_kwargs: Any
    ) -> SnmpClient:
        return SnmpClient(
            host,
            community,
            version=version,
            port=port,
            timeout=0.05,
            retries=0,
            endpoint_factory=agent,
        )

    with (
        patch("custom_components.dolby_cp750.SnmpClient", side_effect=_client),
        patch("custom_components.dolby_cp750.config_flow.SnmpClient", side_effect=_client),
    ):
        yield agent


@pytest.fixture
def mock_setup_entry() -> Generator[AsyncMock]:
    """Skip setting up the entry, for config flow tests."""
    with patch("custom_components.dolby_cp750.async_setup_entry", return_value=True) as setup:
        yield setup


@pytest.fixture
def mock_config_entry() -> MockConfigEntry:
    """Return a config entry for the unit."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="Dolby CP750",
        unique_id=SERIAL,
        data=dict(ENTRY_DATA),
    )


async def setup_integration(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    """Add the entry and set it up."""
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
