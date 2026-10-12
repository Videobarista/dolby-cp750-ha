"""Tests for setting up, polling and unloading the Dolby CP750 integration."""

from __future__ import annotations

from datetime import timedelta
import logging

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.dolby_cp750.const import (
    CONF_SCAN_INTERVAL,
    CONF_SNMP_ENABLED,
    DOMAIN,
    OID_BITSTREAM_FORMAT,
    OID_DIGITAL_VALID,
    OID_METER_LEVELS,
    OID_RELAY_STATUS,
)
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import STATE_OFF, STATE_ON, STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.util import dt as dt_util

from .conftest import ENTRY_DATA, setup_integration
from .fakes import SERIAL, VERSION, FakeCp750, FakeSnmpAgent

MEDIA_PLAYER = "media_player.dolby_cp750"


def _device(hass: HomeAssistant, entry: MockConfigEntry) -> dr.DeviceEntry | None:
    """Return the CP750 device of the entry."""
    for device in dr.async_entries_for_config_entry(dr.async_get(hass), entry.entry_id):
        if (DOMAIN, SERIAL) in device.identifiers:
            return device
    return None


def _own_problems(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    """Return warnings and errors logged by this integration."""
    return [
        record
        for record in caplog.records
        if record.name.startswith("custom_components.dolby_cp750")
        and record.levelno >= logging.WARNING
    ]


async def test_setup_and_unload(
    hass: HomeAssistant,
    fake_unit: FakeCp750,
    fake_agent: FakeSnmpAgent,
    mock_config_entry: MockConfigEntry,
) -> None:
    """The entry loads, creates the device and entities, and unloads cleanly."""
    await setup_integration(hass, mock_config_entry)
    assert mock_config_entry.state is ConfigEntryState.LOADED

    device = _device(hass, mock_config_entry)
    assert device is not None
    assert device.manufacturer == "Dolby Laboratories"
    assert device.model == "CP750"
    assert device.sw_version == VERSION
    assert device.serial_number == SERIAL

    player = hass.states.get(MEDIA_PLAYER)
    assert player.state == STATE_ON
    assert player.attributes["volume_level"] == 0.7
    assert player.attributes["is_volume_muted"] is False
    assert player.attributes["source"] == "Digital 1"
    assert player.attributes["source_list"][0] == "Digital 1"

    assert hass.states.get("number.dolby_cp750_fader").state == "7.0"
    assert hass.states.get("switch.dolby_cp750_mute").state == STATE_OFF
    assert hass.states.get("select.dolby_cp750_input").state == "dig_1"
    assert hass.states.get("select.dolby_cp750_power_on_input").state == "last"
    assert hass.states.get("select.dolby_cp750_pcm_decode_mode_digital_1").state == "lr_discrete"
    assert hass.states.get("binary_sensor.dolby_cp750_connection").state == STATE_ON

    assert hass.states.get("sensor.dolby_cp750_digital_1_signal").state == "valid"
    assert hass.states.get("sensor.dolby_cp750_digital_2_signal").state == "not_available"
    assert hass.states.get("sensor.dolby_cp750_digital_3_signal").state == "invalid"
    assert hass.states.get("sensor.dolby_cp750_bitstream_format").state == "pcm"
    assert hass.states.get("sensor.dolby_cp750_active_decode_mode").state == "lr_discrete"
    assert hass.states.get("binary_sensor.dolby_cp750_output_relays").state == STATE_ON
    restart = dt_util.parse_datetime(hass.states.get("sensor.dolby_cp750_last_restart").state)
    assert restart is not None
    assert abs((dt_util.utcnow() - restart) - timedelta(hours=1)) < timedelta(minutes=1)

    # Settings that are disabled by default are not polled.
    assert "cp750.sys.fader_preset_1 ?" not in fake_unit.received
    assert "cp750.sys.power_on_input ?" in fake_unit.received

    assert await hass.config_entries.async_unload(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    assert mock_config_entry.state is ConfigEntryState.NOT_LOADED
    assert fake_unit.received[-1] == "exit"


async def test_meters_disabled_by_default(
    hass: HomeAssistant,
    fake_unit: FakeCp750,
    fake_agent: FakeSnmpAgent,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Meter sensors exist but are disabled by default."""
    await setup_integration(hass, mock_config_entry)
    entry = er.async_get(hass).async_get("sensor.dolby_cp750_meter_l")
    assert entry is not None
    assert entry.disabled_by is er.RegistryEntryDisabler.INTEGRATION


async def test_meters_when_enabled(
    hass: HomeAssistant,
    fake_unit: FakeCp750,
    fake_agent: FakeSnmpAgent,
    mock_config_entry: MockConfigEntry,
    entity_registry_enabled_by_default: None,
) -> None:
    """Each meter sensor shows its own channel."""
    await setup_integration(hass, mock_config_entry)
    assert hass.states.get("sensor.dolby_cp750_meter_l").state == "10"
    assert hass.states.get("sensor.dolby_cp750_meter_lfe").state == "60"
    assert hass.states.get("sensor.dolby_cp750_meter_re").state == "48"
    # Disabled-by-default settings are polled once enabled.
    assert hass.states.get("number.dolby_cp750_fader_preset_digital_1").state == "7.0"
    assert hass.states.get("switch.dolby_cp750_fader_preset_digital_1_enabled").state == STATE_OFF
    assert hass.states.get("number.dolby_cp750_delay_analog").state == "0"
    assert hass.states.get("number.dolby_cp750_surround_delay").state == "20"
    assert hass.states.get("select.dolby_cp750_non_sync_format").state == "60"
    # "n_a" is a state, not a choice: it shows as unknown.
    assert (
        hass.states.get("select.dolby_cp750_dolby_digital_decode_mode_digital_1").state == "unknown"
    )


async def test_odd_meter_and_snmp_values(
    hass: HomeAssistant,
    fake_unit: FakeCp750,
    fake_agent: FakeSnmpAgent,
    mock_config_entry: MockConfigEntry,
    entity_registry_enabled_by_default: None,
) -> None:
    """Values the MIB does not describe show as unknown instead of failing."""
    fake_agent.objects[OID_METER_LEVELS] = b"10 55"
    fake_agent.objects[OID_BITSTREAM_FORMAT] = b"MPEG"
    fake_agent.objects[OID_DIGITAL_VALID[1]] = b"valid"
    fake_agent.objects[OID_RELAY_STATUS] = 0
    await setup_integration(hass, mock_config_entry)

    assert hass.states.get("sensor.dolby_cp750_meter_l").state == "unknown"
    assert hass.states.get("sensor.dolby_cp750_bitstream_format").state == "unknown"
    assert hass.states.get("sensor.dolby_cp750_digital_1_signal").state == "unknown"
    assert hass.states.get("binary_sensor.dolby_cp750_output_relays").state == "unknown"

    fake_agent.objects[OID_METER_LEVELS] = b"10 55 00 60 10 01 xx 48"
    fake_agent.objects[OID_BITSTREAM_FORMAT] = 5
    fake_agent.objects[OID_RELAY_STATUS] = 2
    await mock_config_entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get("sensor.dolby_cp750_meter_le").state == "unknown"
    assert hass.states.get("sensor.dolby_cp750_bitstream_format").state == "unknown"
    assert hass.states.get("binary_sensor.dolby_cp750_output_relays").state == STATE_OFF


async def test_missing_snmp_object(
    hass: HomeAssistant,
    fake_unit: FakeCp750,
    fake_agent: FakeSnmpAgent,
    mock_config_entry: MockConfigEntry,
) -> None:
    """An object the agent does not have makes only its entity unavailable."""
    del fake_agent.objects[OID_RELAY_STATUS]
    await setup_integration(hass, mock_config_entry)

    assert hass.states.get("binary_sensor.dolby_cp750_output_relays").state == STATE_UNAVAILABLE
    assert hass.states.get("sensor.dolby_cp750_bitstream_format").state == "pcm"


async def test_setup_while_unit_is_off(
    hass: HomeAssistant,
    fake_unit: FakeCp750,
    fake_agent: FakeSnmpAgent,
    mock_config_entry: MockConfigEntry,
) -> None:
    """A switched-off unit does not fail setup: it shows as off and is picked up later."""
    fake_unit.online = False
    await setup_integration(hass, mock_config_entry)

    assert mock_config_entry.state is ConfigEntryState.LOADED
    assert hass.states.get(MEDIA_PLAYER).state == STATE_OFF
    assert hass.states.get("number.dolby_cp750_fader").state == STATE_UNAVAILABLE
    assert hass.states.get("sensor.dolby_cp750_bitstream_format").state == STATE_UNAVAILABLE
    assert hass.states.get("binary_sensor.dolby_cp750_connection").state == STATE_OFF
    device = _device(hass, mock_config_entry)
    assert device is not None
    assert device.sw_version is None

    fake_unit.online = True
    await mock_config_entry.runtime_data.async_refresh()
    await hass.async_block_till_done()

    assert hass.states.get(MEDIA_PLAYER).state == STATE_ON
    assert hass.states.get("number.dolby_cp750_fader").state == "7.0"
    device = _device(hass, mock_config_entry)
    assert device is not None
    assert device.sw_version == VERSION


async def test_wrong_unit_at_setup(
    hass: HomeAssistant,
    fake_unit: FakeCp750,
    fake_agent: FakeSnmpAgent,
    mock_config_entry: MockConfigEntry,
) -> None:
    """A different unit at the stored address fails setup."""
    fake_unit.set_value("cp750.sys.serial_number", "999999")
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert mock_config_entry.state is ConfigEntryState.SETUP_ERROR


async def test_wrong_unit_while_running(
    hass: HomeAssistant,
    fake_unit: FakeCp750,
    fake_agent: FakeSnmpAgent,
    mock_config_entry: MockConfigEntry,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A different unit appearing at the address is not controlled."""
    await setup_integration(hass, mock_config_entry)
    coordinator = mock_config_entry.runtime_data

    fake_unit.set_value("cp750.sys.serial_number", "999999")
    fake_unit.drop_connections()
    await coordinator.async_refresh()
    await coordinator.async_refresh()
    await hass.async_block_till_done()

    assert hass.states.get(MEDIA_PLAYER).state == STATE_OFF
    assert caplog.text.count("has serial number 999999") == 1

    fake_unit.received.clear()
    await hass.services.async_call(
        "media_player",
        "volume_mute",
        {"entity_id": MEDIA_PLAYER, "is_volume_muted": True},
        blocking=True,
    )
    assert "cp750.sys.mute 1" not in fake_unit.received


async def test_unit_switched_off_and_on(
    hass: HomeAssistant,
    fake_unit: FakeCp750,
    fake_agent: FakeSnmpAgent,
    mock_config_entry: MockConfigEntry,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Switching the unit off shows it as off without errors in the log."""
    await setup_integration(hass, mock_config_entry)
    coordinator = mock_config_entry.runtime_data

    fake_unit.drop_connections()
    fake_unit.online = False
    await coordinator.async_refresh()
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get(MEDIA_PLAYER).state == STATE_OFF
    assert hass.states.get("switch.dolby_cp750_mute").state == STATE_UNAVAILABLE
    assert _own_problems(caplog) == []

    fake_unit.online = True
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get(MEDIA_PLAYER).state == STATE_ON
    # The new connection was identified again.
    assert fake_unit.connections == 2
    assert fake_unit.received.count("cp750.sysinfo.version ?") == 2


async def test_unit_stops_answering(
    hass: HomeAssistant,
    fake_unit: FakeCp750,
    fake_agent: FakeSnmpAgent,
    mock_config_entry: MockConfigEntry,
) -> None:
    """A unit that keeps the connection but no longer answers shows as off."""
    await setup_integration(hass, mock_config_entry)
    fake_unit.hang = True
    await mock_config_entry.runtime_data.async_refresh()
    await hass.async_block_till_done()

    assert hass.states.get(MEDIA_PLAYER).state == STATE_OFF


async def test_unsupported_parameter(
    hass: HomeAssistant,
    fake_unit: FakeCp750,
    fake_agent: FakeSnmpAgent,
    mock_config_entry: MockConfigEntry,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A parameter the firmware does not know becomes unavailable after two polls."""
    fake_unit.remove("cp750.sys.power_on_input")
    await setup_integration(hass, mock_config_entry)
    coordinator = mock_config_entry.runtime_data
    assert hass.states.get("select.dolby_cp750_power_on_input").state == "unknown"

    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get("select.dolby_cp750_power_on_input").state == STATE_UNAVAILABLE
    assert "does not answer cp750.sys.power_on_input" in caplog.text
    assert hass.states.get(MEDIA_PLAYER).state == STATE_ON

    # It is no longer asked for.
    fake_unit.received.clear()
    coordinator._slow_due = 0
    await coordinator.async_refresh()
    assert "cp750.sys.power_on_input ?" not in fake_unit.received


async def test_slow_parameters_are_read_once_a_minute(
    hass: HomeAssistant,
    fake_unit: FakeCp750,
    fake_agent: FakeSnmpAgent,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Fast parameters are read every poll, settings only when due."""
    await setup_integration(hass, mock_config_entry)
    coordinator = mock_config_entry.runtime_data

    fake_unit.received.clear()
    await coordinator.async_refresh()
    assert fake_unit.received == [
        "cp750.sys.fader ?",
        "cp750.sys.mute ?",
        "cp750.sys.input_mode ?",
    ]

    fake_unit.received.clear()
    coordinator._slow_due = 0
    await coordinator.async_refresh()
    assert "cp750.sys.power_on_input ?" in fake_unit.received


async def test_snmp_disabled(
    hass: HomeAssistant, fake_unit: FakeCp750, fake_agent: FakeSnmpAgent
) -> None:
    """Without SNMP there are no SNMP entities and the agent is not asked."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Dolby CP750",
        unique_id=SERIAL,
        data={**ENTRY_DATA, CONF_SNMP_ENABLED: False},
    )
    await setup_integration(hass, entry)

    assert hass.states.get(MEDIA_PLAYER).state == STATE_ON
    assert hass.states.get("sensor.dolby_cp750_bitstream_format") is None
    assert hass.states.get("binary_sensor.dolby_cp750_output_relays") is None
    assert fake_agent.requests == []


async def test_snmp_stops_and_returns(
    hass: HomeAssistant,
    fake_unit: FakeCp750,
    fake_agent: FakeSnmpAgent,
    mock_config_entry: MockConfigEntry,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """SNMP going away makes only the SNMP entities unavailable, with one warning."""
    await setup_integration(hass, mock_config_entry)
    coordinator = mock_config_entry.runtime_data

    fake_agent.online = False
    await coordinator.async_refresh()
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get("sensor.dolby_cp750_bitstream_format").state == STATE_UNAVAILABLE
    assert hass.states.get("sensor.dolby_cp750_last_restart").state == STATE_UNAVAILABLE
    assert hass.states.get(MEDIA_PLAYER).state == STATE_ON
    assert caplog.text.count("No SNMP status") == 1

    fake_agent.online = True
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get("sensor.dolby_cp750_bitstream_format").state == "pcm"
    assert "available again" in caplog.text


async def test_options_change_reloads(
    hass: HomeAssistant,
    fake_unit: FakeCp750,
    fake_agent: FakeSnmpAgent,
    mock_config_entry: MockConfigEntry,
) -> None:
    """A new polling interval takes effect after the automatic reload."""
    await setup_integration(hass, mock_config_entry)
    hass.config_entries.async_update_entry(mock_config_entry, options={CONF_SCAN_INTERVAL: 15})
    await hass.async_block_till_done()

    assert mock_config_entry.state is ConfigEntryState.LOADED
    assert mock_config_entry.runtime_data.update_interval == timedelta(seconds=15)
