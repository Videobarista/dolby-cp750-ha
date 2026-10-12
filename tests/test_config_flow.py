"""Tests for the Dolby CP750 config flow."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.dolby_cp750.const import (
    CONF_SCAN_INTERVAL,
    CONF_SERIAL,
    CONF_SNMP_COMMUNITY,
    CONF_SNMP_ENABLED,
    CONF_SNMP_VERSION,
    DEFAULT_PORT,
    DOMAIN,
)
from custom_components.dolby_cp750.snmp import SNMP_V1
from homeassistant.config_entries import SOURCE_USER
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from .conftest import ENTRY_DATA, HOST
from .fakes import SERIAL, FakeCp750, FakeSnmpAgent

pytestmark = pytest.mark.usefixtures("mock_setup_entry")

USER_INPUT = {
    CONF_HOST: HOST,
    CONF_PORT: DEFAULT_PORT,
    CONF_SNMP_ENABLED: True,
    CONF_SNMP_COMMUNITY: "public",
}


async def _start(hass: HomeAssistant) -> str:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    assert result["errors"] == {}
    return result["flow_id"]


async def test_user_flow(
    hass: HomeAssistant, fake_unit: FakeCp750, fake_agent: FakeSnmpAgent
) -> None:
    """A manual setup identifies the unit, checks SNMP and keys the entry by serial."""
    flow_id = await _start(hass)
    result = await hass.config_entries.flow.async_configure(
        flow_id, {**USER_INPUT, CONF_HOST: f"  {HOST} "}
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Dolby CP750"
    assert result["data"] == ENTRY_DATA
    assert result["result"].unique_id == SERIAL
    # The validation connection was closed politely.
    assert fake_unit.received[-1] == "exit"


async def test_user_flow_snmp_v1(
    hass: HomeAssistant, fake_unit: FakeCp750, fake_agent: FakeSnmpAgent
) -> None:
    """An agent that only speaks SNMPv1 is stored as such."""
    fake_agent.versions = {SNMP_V1}
    flow_id = await _start(hass)
    result = await hass.config_entries.flow.async_configure(flow_id, USER_INPUT)

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_SNMP_VERSION] == "1"


async def test_user_flow_without_snmp(
    hass: HomeAssistant, fake_unit: FakeCp750, fake_agent: FakeSnmpAgent
) -> None:
    """With SNMP off the agent is not contacted."""
    flow_id = await _start(hass)
    result = await hass.config_entries.flow.async_configure(
        flow_id, {**USER_INPUT, CONF_SNMP_ENABLED: False}
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_SNMP_ENABLED] is False
    assert result["data"][CONF_SNMP_VERSION] is None
    assert fake_agent.requests == []


async def test_user_flow_without_serial(
    hass: HomeAssistant, fake_unit: FakeCp750, fake_agent: FakeSnmpAgent
) -> None:
    """A unit that does not report a serial number is keyed by its address."""
    fake_unit.remove("cp750.sys.serial_number")
    flow_id = await _start(hass)
    result = await hass.config_entries.flow.async_configure(flow_id, USER_INPUT)

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_SERIAL] is None
    assert result["result"].unique_id == HOST


@pytest.mark.parametrize(
    ("break_it", "error"),
    [
        ("offline", "cannot_connect"),
        ("not_cp750", "not_cp750"),
        ("snmp", "snmp_cannot_connect"),
    ],
)
async def test_user_flow_errors(
    hass: HomeAssistant,
    fake_unit: FakeCp750,
    fake_agent: FakeSnmpAgent,
    break_it: str,
    error: str,
) -> None:
    """Errors are shown on the form and the flow recovers afterwards."""
    if break_it == "offline":
        fake_unit.online = False
    elif break_it == "not_cp750":
        fake_unit.hang = True
    else:
        fake_agent.online = False

    flow_id = await _start(hass)
    result = await hass.config_entries.flow.async_configure(flow_id, USER_INPUT)
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": error}

    fake_unit.online = True
    fake_unit.hang = False
    fake_agent.online = True
    result = await hass.config_entries.flow.async_configure(flow_id, USER_INPUT)
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_user_flow_unexpected_error(
    hass: HomeAssistant, fake_unit: FakeCp750, fake_agent: FakeSnmpAgent
) -> None:
    """An unexpected exception is logged and shown as unknown."""
    flow_id = await _start(hass)
    with patch(
        "custom_components.dolby_cp750.config_flow._async_validate",
        side_effect=RuntimeError("boom"),
    ):
        result = await hass.config_entries.flow.async_configure(flow_id, USER_INPUT)
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "unknown"}


async def test_user_flow_already_configured(
    hass: HomeAssistant,
    fake_unit: FakeCp750,
    fake_agent: FakeSnmpAgent,
    mock_config_entry: MockConfigEntry,
) -> None:
    """The same unit cannot be added twice; a new address is taken over."""
    mock_config_entry.add_to_hass(hass)
    flow_id = await _start(hass)
    result = await hass.config_entries.flow.async_configure(
        flow_id, {**USER_INPUT, CONF_HOST: "192.0.2.20"}
    )

    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    assert mock_config_entry.data[CONF_HOST] == "192.0.2.20"


async def test_reconfigure_flow(
    hass: HomeAssistant,
    fake_unit: FakeCp750,
    fake_agent: FakeSnmpAgent,
    mock_config_entry: MockConfigEntry,
) -> None:
    """The address and SNMP settings can be changed."""
    mock_config_entry.add_to_hass(hass)
    result = await mock_config_entry.start_reconfigure_flow(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reconfigure"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {**USER_INPUT, CONF_HOST: "192.0.2.30", CONF_SNMP_ENABLED: False},
    )
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert mock_config_entry.data[CONF_HOST] == "192.0.2.30"
    assert mock_config_entry.data[CONF_SNMP_ENABLED] is False


async def test_reconfigure_flow_error(
    hass: HomeAssistant,
    fake_unit: FakeCp750,
    fake_agent: FakeSnmpAgent,
    mock_config_entry: MockConfigEntry,
) -> None:
    """An unreachable address shows an error and can be corrected."""
    mock_config_entry.add_to_hass(hass)
    result = await mock_config_entry.start_reconfigure_flow(hass)

    fake_unit.online = False
    result = await hass.config_entries.flow.async_configure(result["flow_id"], USER_INPUT)
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}

    fake_unit.online = True
    result = await hass.config_entries.flow.async_configure(result["flow_id"], USER_INPUT)
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"


async def test_reconfigure_wrong_device(
    hass: HomeAssistant,
    fake_unit: FakeCp750,
    fake_agent: FakeSnmpAgent,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Pointing an entry at another unit is refused."""
    mock_config_entry.add_to_hass(hass)
    fake_unit.set_value("cp750.sys.serial_number", "999999")
    result = await mock_config_entry.start_reconfigure_flow(hass)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], USER_INPUT)

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "wrong_device"
    assert mock_config_entry.data[CONF_HOST] == HOST


async def test_reconfigure_entry_without_serial(
    hass: HomeAssistant, fake_unit: FakeCp750, fake_agent: FakeSnmpAgent
) -> None:
    """An entry keyed by address follows the new address."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Dolby CP750",
        unique_id=HOST,
        data={**ENTRY_DATA, CONF_SERIAL: None},
    )
    entry.add_to_hass(hass)
    fake_unit.remove("cp750.sys.serial_number")

    result = await entry.start_reconfigure_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {**USER_INPUT, CONF_HOST: "192.0.2.40"}
    )
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert entry.unique_id == "192.0.2.40"
    assert entry.data[CONF_HOST] == "192.0.2.40"


async def test_options_flow(hass: HomeAssistant, mock_config_entry: MockConfigEntry) -> None:
    """The polling interval is stored as a whole number of seconds."""
    mock_config_entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(mock_config_entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "init"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_SCAN_INTERVAL: 10.0}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert mock_config_entry.options == {CONF_SCAN_INTERVAL: 10}
