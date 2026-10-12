"""Base entities for the Dolby CP750 integration."""

from __future__ import annotations

from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .coordinator import Cp750Coordinator


class Cp750Entity(CoordinatorEntity[Cp750Coordinator]):
    """Entity that belongs to one CP750."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: Cp750Coordinator, key: str) -> None:
        """Initialize the entity; ``key`` makes the unique ID."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.unique_base}_{key}"
        self._attr_device_info = coordinator.device_info


class Cp750ProtocolEntity(Cp750Entity):
    """Entity backed by one parameter of the ASCII protocol."""

    def __init__(self, coordinator: Cp750Coordinator, key: str, parameter: str) -> None:
        """Initialize the entity for protocol parameter ``parameter``."""
        super().__init__(coordinator, key)
        self.parameter = parameter

    async def async_added_to_hass(self) -> None:
        """Ask the coordinator to poll this entity's parameter."""
        await super().async_added_to_hass()
        self.async_on_remove(self.coordinator.async_register_key(self.parameter))

    @property
    def available(self) -> bool:
        """Available while the unit answers and supports the parameter."""
        return (
            super().available
            and self.coordinator.data.reachable
            and self.coordinator.is_supported(self.parameter)
        )

    @property
    def raw_value(self) -> str | None:
        """Return the value of the parameter as reported by the unit."""
        return self.coordinator.data.values.get(self.parameter)


class Cp750SnmpEntity(Cp750Entity):
    """Entity backed by one object of the CP750 SNMP MIB."""

    def __init__(self, coordinator: Cp750Coordinator, key: str, oid: str) -> None:
        """Initialize the entity for SNMP object ``oid``."""
        super().__init__(coordinator, key)
        self.oid = oid

    @property
    def available(self) -> bool:
        """Available while SNMP answers and the agent has the object."""
        data = self.coordinator.data
        return (
            super().available
            and data.reachable
            and data.snmp_ok
            and data.snmp.get(self.oid) is not None
        )

    @property
    def snmp_value(self) -> int | str | None:
        """Return the value of the object."""
        return self.coordinator.data.snmp.get(self.oid)
