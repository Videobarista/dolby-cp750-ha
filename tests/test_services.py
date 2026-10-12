"""Tests for the send_command action."""

from __future__ import annotations

from typing import Any

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.dolby_cp750.const import DOMAIN
from custom_components.dolby_cp750.services import SERVICE_SEND_COMMAND
from homeassistant.auth.models import User
from homeassistant.core import Context, HomeAssistant
from homeassistant.exceptions import (
    HomeAssistantError,
    ServiceValidationError,
    Unauthorized,
    UnknownUser,
)

from .conftest import setup_integration
from .fakes import FakeCp750

pytestmark = pytest.mark.usefixtures("fake_agent")


async def _send(
    hass: HomeAssistant, entry_id: str, command: str, context: Context | None = None
) -> Any:
    return await hass.services.async_call(
        DOMAIN,
        SERVICE_SEND_COMMAND,
        {"config_entry_id": entry_id, "command": command},
        blocking=True,
        return_response=True,
        context=context,
    )


async def test_send_command(
    hass: HomeAssistant, fake_unit: FakeCp750, mock_config_entry: MockConfigEntry
) -> None:
    """A command returns the reply lines and the new state is shown."""
    await setup_integration(hass, mock_config_entry)

    response = await _send(hass, mock_config_entry.entry_id, "  cp750.sys.fader 45 ")
    await hass.async_block_till_done()
    assert response == {"lines": ["cp750.sys.fader 45"]}
    assert hass.states.get("number.dolby_cp750_fader").state == "4.5"

    response = await _send(hass, mock_config_entry.entry_id, "status")
    assert "cp750.sys.mute : 0" in response["lines"]


async def test_send_command_invalid(
    hass: HomeAssistant, fake_unit: FakeCp750, mock_config_entry: MockConfigEntry
) -> None:
    """Commands with characters outside printable ASCII are refused."""
    await setup_integration(hass, mock_config_entry)
    with pytest.raises(ServiceValidationError):
        await _send(hass, mock_config_entry.entry_id, "fadér ?")


async def test_send_command_unknown_entry(
    hass: HomeAssistant, fake_unit: FakeCp750, mock_config_entry: MockConfigEntry
) -> None:
    """An entry ID that is not a CP750 is refused."""
    await setup_integration(hass, mock_config_entry)
    with pytest.raises(ServiceValidationError):
        await _send(hass, "no-such-entry", "status")


async def test_send_command_entry_not_loaded(
    hass: HomeAssistant, fake_unit: FakeCp750, mock_config_entry: MockConfigEntry
) -> None:
    """An unloaded entry is refused."""
    await setup_integration(hass, mock_config_entry)
    await hass.config_entries.async_unload(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    with pytest.raises(ServiceValidationError):
        await _send(hass, mock_config_entry.entry_id, "status")


async def test_send_command_unit_off(
    hass: HomeAssistant, fake_unit: FakeCp750, mock_config_entry: MockConfigEntry
) -> None:
    """A unit that is off makes the action fail with an error."""
    await setup_integration(hass, mock_config_entry)
    fake_unit.drop_connections()
    fake_unit.online = False

    with pytest.raises(HomeAssistantError):
        await _send(hass, mock_config_entry.entry_id, "status")


async def test_send_command_wrong_unit(
    hass: HomeAssistant, fake_unit: FakeCp750, mock_config_entry: MockConfigEntry
) -> None:
    """Commands are not sent to a different unit at the address."""
    await setup_integration(hass, mock_config_entry)
    fake_unit.set_value("cp750.sys.serial_number", "999999")
    fake_unit.drop_connections()
    # The first poll notices the closed connection, the second one the new unit.
    await mock_config_entry.runtime_data.async_refresh()
    await mock_config_entry.runtime_data.async_refresh()

    fake_unit.received.clear()
    with pytest.raises(HomeAssistantError):
        await _send(hass, mock_config_entry.entry_id, "cp750.sys.mute 1")
    assert "cp750.sys.mute 1" not in fake_unit.received


async def test_send_command_admin_only(
    hass: HomeAssistant,
    fake_unit: FakeCp750,
    mock_config_entry: MockConfigEntry,
    hass_admin_user: User,
    hass_read_only_user: User,
) -> None:
    """Administrators may send raw commands, other users may not."""
    await setup_integration(hass, mock_config_entry)

    response = await _send(
        hass, mock_config_entry.entry_id, "cp750.sys.mute ?", Context(user_id=hass_admin_user.id)
    )
    assert response == {"lines": ["cp750.sys.mute 0"]}

    with pytest.raises(Unauthorized):
        await _send(
            hass,
            mock_config_entry.entry_id,
            "cp750.sys.mute 1",
            Context(user_id=hass_read_only_user.id),
        )
    with pytest.raises(UnknownUser):
        await _send(hass, mock_config_entry.entry_id, "cp750.sys.mute 1", Context(user_id="nobody"))
    assert fake_unit.value("cp750.sys.mute") == "0"
