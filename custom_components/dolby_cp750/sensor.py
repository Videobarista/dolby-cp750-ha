"""Sensors for the Dolby CP750, read through SNMP (DOLBY-CP750-MIB)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
import logging

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import Cp750ConfigEntry
from .const import (
    ACTIVE_DECODE_MODES,
    BITSTREAM_FORMATS,
    METER_CHANNELS,
    OID_BITSTREAM_FORMAT,
    OID_DECODE_MODE,
    OID_DIGITAL_VALID,
    OID_METER_LEVELS,
    OID_SYS_UPTIME,
    SIGNAL_STATES,
)
from .coordinator import Cp750Coordinator
from .entity import Cp750Entity, Cp750SnmpEntity

_LOGGER = logging.getLogger(__name__)

# Entities only read coordinator data.
PARALLEL_UPDATES = 0


def _signal(value: int | str | None) -> str | None:
    return SIGNAL_STATES.get(value) if isinstance(value, int) else None


def _text_enum(options: tuple[str, ...]) -> Callable[[int | str | None], str | None]:
    """Map a text value such as 'Dolby_Digital' or 'n_a' onto an enum option."""

    def _convert(value: int | str | None) -> str | None:
        if not isinstance(value, str):
            return None
        option = value.strip().lower()
        if option == "n_a":
            option = "not_available"
        if option in options:
            return option
        _LOGGER.debug("Unknown value %r, expected one of %s", value, options)
        return None

    return _convert


def _meter(index: int) -> Callable[[int | str | None], int | None]:
    """Pick one channel from the 'L C R LFE Ls Rs Le Re' meter string."""

    def _convert(value: int | str | None) -> int | None:
        if not isinstance(value, str):
            return None
        parts = value.split()
        if len(parts) != len(METER_CHANNELS):
            return None
        try:
            return int(parts[index])
        except ValueError:
            return None

    return _convert


@dataclass(frozen=True, kw_only=True)
class Cp750SnmpSensorDescription(SensorEntityDescription):
    """Describes a sensor backed by one SNMP object."""

    oid: str
    convert: Callable[[int | str | None], str | int | None]


SNMP_SENSORS: tuple[Cp750SnmpSensorDescription, ...] = (
    *(
        Cp750SnmpSensorDescription(
            key=f"dig_{number}_signal",
            translation_key=f"dig_{number}_signal",
            oid=oid,
            convert=_signal,
            device_class=SensorDeviceClass.ENUM,
            options=list(SIGNAL_STATES.values()),
        )
        for number, oid in OID_DIGITAL_VALID.items()
    ),
    Cp750SnmpSensorDescription(
        key="bitstream_format",
        translation_key="bitstream_format",
        oid=OID_BITSTREAM_FORMAT,
        convert=_text_enum(BITSTREAM_FORMATS),
        device_class=SensorDeviceClass.ENUM,
        options=list(BITSTREAM_FORMATS),
    ),
    Cp750SnmpSensorDescription(
        key="active_decode_mode",
        translation_key="active_decode_mode",
        oid=OID_DECODE_MODE,
        convert=_text_enum(ACTIVE_DECODE_MODES),
        device_class=SensorDeviceClass.ENUM,
        options=list(ACTIVE_DECODE_MODES),
    ),
    *(
        Cp750SnmpSensorDescription(
            key=f"meter_{channel}",
            translation_key=f"meter_{channel}",
            oid=OID_METER_LEVELS,
            convert=_meter(index),
            state_class=SensorStateClass.MEASUREMENT,
            entity_registry_enabled_default=False,
        )
        for index, channel in enumerate(METER_CHANNELS)
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: Cp750ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the sensors; they need SNMP."""
    coordinator = entry.runtime_data
    if coordinator.snmp_client is None:
        return
    entities: list[SensorEntity] = [
        Cp750SnmpSensor(coordinator, description) for description in SNMP_SENSORS
    ]
    entities.append(Cp750LastRestartSensor(coordinator))
    async_add_entities(entities)


class Cp750SnmpSensor(Cp750SnmpEntity, SensorEntity):
    """A status value from the CP750 MIB."""

    entity_description: Cp750SnmpSensorDescription

    def __init__(
        self, coordinator: Cp750Coordinator, description: Cp750SnmpSensorDescription
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, description.key, description.oid)
        self.entity_description = description

    @property
    def native_value(self) -> str | int | None:
        """Return the converted value."""
        return self.entity_description.convert(self.snmp_value)


class Cp750LastRestartSensor(Cp750Entity, SensorEntity):
    """When the unit last started, derived from the SNMP agent's uptime."""

    _attr_translation_key = "last_restart"
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: Cp750Coordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, "last_restart")

    @property
    def available(self) -> bool:
        """Available while SNMP reports an uptime."""
        data = self.coordinator.data
        return (
            super().available
            and data.reachable
            and data.snmp_ok
            and (data.snmp.get(OID_SYS_UPTIME) is not None)
        )

    @property
    def native_value(self) -> datetime | None:
        """Return the time of the last restart."""
        return self.coordinator.data.boot_time
