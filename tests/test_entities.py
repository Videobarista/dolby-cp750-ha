"""Tests for controlling the CP750 through its entities."""

from __future__ import annotations

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant.const import ATTR_ENTITY_ID, STATE_OFF, STATE_ON
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError

from .conftest import setup_integration
from .fakes import FakeCp750

MEDIA_PLAYER = "media_player.dolby_cp750"

pytestmark = pytest.mark.usefixtures("fake_agent")


@pytest.fixture
async def loaded(
    hass: HomeAssistant, fake_unit: FakeCp750, mock_config_entry: MockConfigEntry
) -> MockConfigEntry:
    """Set up the integration with all entities enabled."""
    await setup_integration(hass, mock_config_entry)
    return mock_config_entry


async def _call(hass: HomeAssistant, domain: str, service: str, entity_id: str, **data) -> None:
    await hass.services.async_call(
        domain, service, {ATTR_ENTITY_ID: entity_id, **data}, blocking=True
    )


@pytest.mark.usefixtures("loaded")
async def test_media_player_volume(hass: HomeAssistant, fake_unit: FakeCp750) -> None:
    """Volume maps onto the fader; up and down move it by 0.1."""
    await _call(hass, "media_player", "volume_set", MEDIA_PLAYER, volume_level=0.55)
    assert fake_unit.value("cp750.sys.fader") == "55"
    assert hass.states.get(MEDIA_PLAYER).attributes["volume_level"] == 0.55
    assert hass.states.get("number.dolby_cp750_fader").state == "5.5"

    await _call(hass, "media_player", "volume_up", MEDIA_PLAYER)
    assert fake_unit.value("cp750.sys.fader") == "56"
    await _call(hass, "media_player", "volume_down", MEDIA_PLAYER)
    await _call(hass, "media_player", "volume_down", MEDIA_PLAYER)
    assert fake_unit.value("cp750.sys.fader") == "54"


@pytest.mark.usefixtures("loaded")
async def test_volume_up_at_maximum(hass: HomeAssistant, fake_unit: FakeCp750) -> None:
    """At 10.0 volume up sends nothing."""
    await _call(hass, "media_player", "volume_set", MEDIA_PLAYER, volume_level=1.0)
    fake_unit.received.clear()

    await _call(hass, "media_player", "volume_up", MEDIA_PLAYER)
    assert fake_unit.received == ["cp750.sys.fader ?"]
    assert fake_unit.value("cp750.sys.fader") == "100"


@pytest.mark.usefixtures("loaded")
async def test_media_player_mute_and_source(hass: HomeAssistant, fake_unit: FakeCp750) -> None:
    """Mute and source selection reach the unit."""
    await _call(hass, "media_player", "volume_mute", MEDIA_PLAYER, is_volume_muted=True)
    assert fake_unit.value("cp750.sys.mute") == "1"
    assert hass.states.get(MEDIA_PLAYER).attributes["is_volume_muted"] is True
    assert hass.states.get("switch.dolby_cp750_mute").state == STATE_ON

    await _call(hass, "media_player", "select_source", MEDIA_PLAYER, source="Non-sync")
    assert fake_unit.value("cp750.sys.input_mode") == "non_sync"
    assert hass.states.get(MEDIA_PLAYER).attributes["source"] == "Non-sync"
    assert hass.states.get("select.dolby_cp750_input").state == "non_sync"


@pytest.mark.usefixtures("loaded")
async def test_media_player_unknown_source(hass: HomeAssistant, fake_unit: FakeCp750) -> None:
    """An unknown source name is refused with a clear error."""
    with pytest.raises(ServiceValidationError):
        await _call(hass, "media_player", "select_source", MEDIA_PLAYER, source="HDMI 1")
    assert fake_unit.value("cp750.sys.input_mode") == "dig_1"


@pytest.mark.usefixtures("loaded")
async def test_input_change_reads_fader(hass: HomeAssistant, fake_unit: FakeCp750) -> None:
    """After an input change the fader is read again (presets may apply)."""
    fake_unit.received.clear()
    await _call(hass, "select", "select_option", "select.dolby_cp750_input", option="dig_3")

    assert fake_unit.received == [
        "cp750.sys.input_mode dig_3",
        "cp750.sys.fader ?",
        "cp750.sys.mute ?",
    ]
    assert hass.states.get("select.dolby_cp750_input").state == "dig_3"


@pytest.mark.usefixtures("loaded")
async def test_previous_input_button(hass: HomeAssistant, fake_unit: FakeCp750) -> None:
    """The button switches back to the previous input."""
    await _call(hass, "select", "select_option", "select.dolby_cp750_input", option="analog")
    await _call(hass, "button", "press", "button.dolby_cp750_previous_input")

    assert fake_unit.value("cp750.sys.input_mode") == "dig_1"
    assert hass.states.get(MEDIA_PLAYER).attributes["source"] == "Digital 1"


@pytest.mark.usefixtures("loaded")
async def test_number_fader(hass: HomeAssistant, fake_unit: FakeCp750) -> None:
    """The fader number uses the Dolby scale of 0.0 to 10.0."""
    await _call(hass, "number", "set_value", "number.dolby_cp750_fader", value=6.5)
    assert fake_unit.value("cp750.sys.fader") == "65"
    assert hass.states.get("number.dolby_cp750_fader").state == "6.5"


@pytest.mark.usefixtures("loaded")
async def test_switch_mute(hass: HomeAssistant, fake_unit: FakeCp750) -> None:
    """The mute switch turns mute on and off."""
    await _call(hass, "switch", "turn_on", "switch.dolby_cp750_mute")
    assert fake_unit.value("cp750.sys.mute") == "1"
    await _call(hass, "switch", "turn_off", "switch.dolby_cp750_mute")
    assert fake_unit.value("cp750.sys.mute") == "0"
    assert hass.states.get("switch.dolby_cp750_mute").state == STATE_OFF


@pytest.mark.usefixtures("loaded")
async def test_select_decode_mode(hass: HomeAssistant, fake_unit: FakeCp750) -> None:
    """Switching digital 1 to Dolby Surround 7.1, like the server cues do."""
    await _call(
        hass,
        "select",
        "select_option",
        "select.dolby_cp750_pcm_decode_mode_digital_1",
        option="4_discrete_sur",
    )
    assert fake_unit.value("cp750.sys.pcm_2_channel_decode_mode_1") == "4_discrete_sur"
    assert hass.states.get("select.dolby_cp750_pcm_decode_mode_digital_1").state == "4_discrete_sur"


@pytest.mark.usefixtures("entity_registry_enabled_by_default", "loaded")
async def test_config_entities(hass: HomeAssistant, fake_unit: FakeCp750) -> None:
    """Presets, preset enables and delays are written to the unit."""
    await _call(
        hass, "number", "set_value", "number.dolby_cp750_fader_preset_microphone", value=4.5
    )
    assert fake_unit.value("cp750.sys.fader_preset_m") == "45"

    await _call(hass, "switch", "turn_on", "switch.dolby_cp750_fader_preset_non_sync_enabled")
    assert fake_unit.value("cp750.sys.fader_preset_n_enable") == "1"

    await _call(hass, "number", "set_value", "number.dolby_cp750_delay_digital_2", value=40)
    assert fake_unit.value("cp750.sys.dig_2_global_delay") == "40"
    assert hass.states.get("number.dolby_cp750_delay_digital_2").state == "40"

    await _call(hass, "select", "select_option", "select.dolby_cp750_non_sync_format", option="71")
    assert fake_unit.value("cp750.sys.non_sync_format") == "71"


async def test_unit_keeps_its_value(
    hass: HomeAssistant, fake_unit: FakeCp750, loaded: MockConfigEntry
) -> None:
    """When the unit refuses a value, the entity shows what the unit reports."""
    await loaded.runtime_data.async_set("cp750.sys.fader", 250)
    await hass.async_block_till_done()
    assert hass.states.get("number.dolby_cp750_fader").state == "7.0"


async def test_command_while_unit_is_off(
    hass: HomeAssistant,
    fake_unit: FakeCp750,
    loaded: MockConfigEntry,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Controls used while the unit is off fail quietly; the player shows off."""
    fake_unit.drop_connections()
    fake_unit.online = False
    await loaded.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get(MEDIA_PLAYER).state == STATE_OFF
    attributes = hass.states.get(MEDIA_PLAYER).attributes
    assert "volume_level" not in attributes
    assert "source" not in attributes

    caplog.clear()
    await _call(hass, "media_player", "volume_mute", MEDIA_PLAYER, is_volume_muted=True)
    await _call(hass, "media_player", "volume_up", MEDIA_PLAYER)
    await hass.async_block_till_done()

    assert hass.states.get(MEDIA_PLAYER).state == STATE_OFF
    assert not [
        record
        for record in caplog.records
        if record.name.startswith("custom_components.dolby_cp750") and record.levelname != "DEBUG"
    ]
