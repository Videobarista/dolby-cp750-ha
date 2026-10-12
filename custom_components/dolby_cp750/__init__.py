"""The Dolby CP750 integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PORT, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType

from .api import Cp750Client
from .const import (
    CONF_SNMP_COMMUNITY,
    CONF_SNMP_ENABLED,
    CONF_SNMP_VERSION,
    DEFAULT_PORT,
    DEFAULT_SNMP_COMMUNITY,
    DOMAIN,
    SNMP_PORT,
)
from .coordinator import Cp750Coordinator
from .services import async_setup_services
from .snmp import SNMP_V2C, VERSIONS_BY_NAME, SnmpClient

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.MEDIA_PLAYER,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.SWITCH,
]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

type Cp750ConfigEntry = ConfigEntry[Cp750Coordinator]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the integration's actions."""
    async_setup_services(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: Cp750ConfigEntry) -> bool:
    """Set up a CP750 from a config entry."""
    host = entry.data[CONF_HOST]
    client = Cp750Client(host, entry.data.get(CONF_PORT, DEFAULT_PORT))
    snmp_client: SnmpClient | None = None
    if entry.data.get(CONF_SNMP_ENABLED):
        snmp_client = SnmpClient(
            host,
            entry.data.get(CONF_SNMP_COMMUNITY, DEFAULT_SNMP_COMMUNITY),
            version=VERSIONS_BY_NAME.get(entry.data.get(CONF_SNMP_VERSION, "2c"), SNMP_V2C),
            port=SNMP_PORT,
        )

    coordinator = Cp750Coordinator(hass, entry, client, snmp_client)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    if coordinator.data.reachable:
        # Read the settings the entities just registered, so they do not wait
        # a full poll interval for their first value.
        await coordinator.async_refresh()

    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def _async_update_listener(hass: HomeAssistant, entry: Cp750ConfigEntry) -> None:
    """Reload the entry when its options change."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: Cp750ConfigEntry) -> bool:
    """Unload a config entry and close the connection to the unit."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        await entry.runtime_data.client.disconnect()
    return unload_ok
