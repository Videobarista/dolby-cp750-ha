"""Binary sensors for the Dolby CP750: connection and output relays."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import Cp750ConfigEntry
from .const import OID_RELAY_STATUS, RELAY_DISENGAGED, RELAY_ENGAGED
from .coordinator import Cp750Coordinator
from .entity import Cp750Entity, Cp750SnmpEntity

# Entities only read coordinator data.
PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: Cp750ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the binary sensors."""
    coordinator = entry.runtime_data
    entities: list[BinarySensorEntity] = [Cp750ConnectionSensor(coordinator)]
    if coordinator.snmp_client is not None:
        entities.append(Cp750RelaySensor(coordinator))
    async_add_entities(entities)


class Cp750ConnectionSensor(Cp750Entity, BinarySensorEntity):
    """On while the unit answers on its control port."""

    _attr_translation_key = "connection"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: Cp750Coordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, "connection")

    @property
    def is_on(self) -> bool:
        """Return True while the unit answers."""
        return self.coordinator.data.reachable


class Cp750RelaySensor(Cp750SnmpEntity, BinarySensorEntity):
    """On while the output relays are engaged (cp750RelayStatus)."""

    _attr_translation_key = "output_relays"

    def __init__(self, coordinator: Cp750Coordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, "output_relays", OID_RELAY_STATUS)

    @property
    def is_on(self) -> bool | None:
        """Return True when engaged, False when disengaged."""
        value = self.snmp_value
        if value == RELAY_ENGAGED:
            return True
        if value == RELAY_DISENGAGED:
            return False
        return None
