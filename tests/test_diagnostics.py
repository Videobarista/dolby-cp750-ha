"""Tests for the Dolby CP750 diagnostics."""

from __future__ import annotations

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.dolby_cp750.const import OID_DIGITAL_VALID, OID_SERIAL, OID_SYS_UPTIME
from custom_components.dolby_cp750.diagnostics import REDACTED, async_get_config_entry_diagnostics
from homeassistant.core import HomeAssistant

from .conftest import setup_integration
from .fakes import SERIAL, VERSION, FakeCp750, FakeSnmpAgent


async def test_diagnostics(
    hass: HomeAssistant,
    fake_unit: FakeCp750,
    fake_agent: FakeSnmpAgent,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Diagnostics show the state, the raw status output and the SNMP walk."""
    del fake_agent.objects[OID_DIGITAL_VALID[4]]
    await setup_integration(hass, mock_config_entry)

    result = await async_get_config_entry_diagnostics(hass, mock_config_entry)

    assert result["entry"]["data"]["serial"] == REDACTED
    assert result["entry"]["data"]["snmp_community"] == REDACTED
    assert result["firmware"] == VERSION
    assert result["reachable"] is True
    assert result["values"]["cp750.sys.fader"] == "70"
    assert "cp750.sys.power_on_input" in result["registered_parameters"]
    assert result["unsupported_parameters"] == []

    assert result["snmp"]["enabled"] is True
    assert result["snmp"]["ok"] is True
    assert result["snmp"]["values"][OID_SYS_UPTIME] == 360_000
    assert result["snmp"]["values"][OID_DIGITAL_VALID[4]] is None

    assert "cp750.sys.fader : 70" in result["status_command"]
    assert REDACTED in result["status_command"]
    assert not any(SERIAL in line for line in result["status_command"])

    walk = result["snmp_walk"]
    assert walk[OID_SERIAL] == REDACTED
    assert all(oid.startswith("1.3.6.1.4.1.6729.") for oid in walk)
    assert str(SERIAL) not in str(result)


async def test_diagnostics_unit_off(
    hass: HomeAssistant,
    fake_unit: FakeCp750,
    fake_agent: FakeSnmpAgent,
    mock_config_entry: MockConfigEntry,
) -> None:
    """With the unit off only the stored state is returned."""
    fake_unit.online = False
    await setup_integration(hass, mock_config_entry)

    result = await async_get_config_entry_diagnostics(hass, mock_config_entry)
    assert result["reachable"] is False
    assert result["firmware"] is None
    assert "status_command" not in result
    assert "snmp_walk" not in result


async def test_diagnostics_partial_failures(
    hass: HomeAssistant,
    fake_unit: FakeCp750,
    fake_agent: FakeSnmpAgent,
    mock_config_entry: MockConfigEntry,
) -> None:
    """A failing status command or SNMP walk is reported, not raised."""
    await setup_integration(hass, mock_config_entry)
    fake_unit.fail_writes = True
    fake_agent.online = False

    result = await async_get_config_entry_diagnostics(hass, mock_config_entry)
    assert result["status_command"].startswith("failed:")
    assert result["snmp_walk"].startswith("failed:")
