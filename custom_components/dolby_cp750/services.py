"""Actions of the Dolby CP750 integration."""

from __future__ import annotations

from typing import TYPE_CHECKING

import voluptuous as vol

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
    callback,
)
from homeassistant.exceptions import (
    HomeAssistantError,
    ServiceValidationError,
    Unauthorized,
    UnknownUser,
)
from homeassistant.helpers import config_validation as cv

from .api import Cp750Error
from .const import DOMAIN

if TYPE_CHECKING:
    from . import Cp750ConfigEntry

SERVICE_SEND_COMMAND = "send_command"
ATTR_CONFIG_ENTRY_ID = "config_entry_id"
ATTR_COMMAND = "command"

SEND_COMMAND_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_CONFIG_ENTRY_ID): cv.string,
        vol.Required(ATTR_COMMAND): cv.string,
    }
)


def _get_entry(hass: HomeAssistant, entry_id: str) -> Cp750ConfigEntry:
    """Return a loaded CP750 config entry or raise a validation error."""
    entry = hass.config_entries.async_get_entry(entry_id)
    if entry is None or entry.domain != DOMAIN:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="entry_not_found",
            translation_placeholders={"entry_id": entry_id},
        )
    if entry.state is not ConfigEntryState.LOADED:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="entry_not_loaded",
            translation_placeholders={"name": entry.title},
        )
    return entry


async def _async_send_command(call: ServiceCall) -> ServiceResponse:
    """Send one raw command line to the unit and return the reply lines.

    Raw commands can change network settings or restart the unit, so only
    administrators (and automations, which have no user) may use this action.
    """
    if call.context.user_id:
        user = await call.hass.auth.async_get_user(call.context.user_id)
        if user is None:
            raise UnknownUser(context=call.context)
        if not user.is_admin:
            raise Unauthorized(context=call.context)

    entry = _get_entry(call.hass, call.data[ATTR_CONFIG_ENTRY_ID])
    command: str = call.data[ATTR_COMMAND].strip()
    if not command or not all(" " <= char <= "~" for char in command):
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="invalid_command",
        )
    try:
        lines = await entry.runtime_data.async_send_raw(command)
    except Cp750Error as err:
        raise HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="command_failed",
            translation_placeholders={"name": entry.title, "error": str(err)},
        ) from err
    return {"lines": [*lines]}


@callback
def async_setup_services(hass: HomeAssistant) -> None:
    """Register the integration's actions."""
    hass.services.async_register(
        DOMAIN,
        SERVICE_SEND_COMMAND,
        _async_send_command,
        schema=SEND_COMMAND_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
