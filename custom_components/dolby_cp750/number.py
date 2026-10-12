"""Number entities for the Dolby CP750: fader, fader presets and delays."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.number import NumberEntity, NumberEntityDescription, NumberMode
from homeassistant.const import EntityCategory, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import Cp750ConfigEntry
from .const import (
    DELAY_MAX,
    FADER_MAX,
    INPUTS,
    KEY_FADER,
    KEY_SURROUND_DELAY,
    PRESET_INPUTS,
    SURROUND_DELAY_MAX,
)
from .coordinator import Cp750Coordinator
from .entity import Cp750ProtocolEntity

PARALLEL_UPDATES = 1


@dataclass(frozen=True, kw_only=True)
class Cp750NumberDescription(NumberEntityDescription):
    """Describes a number backed by a protocol parameter."""

    parameter: str
    # The entity shows the protocol value divided by this factor.
    scale: int = 1


def _fader(
    key: str,
    parameter: str,
    translation_key: str,
    *,
    mode: NumberMode,
    entity_category: EntityCategory | None = None,
    enabled_default: bool = True,
) -> Cp750NumberDescription:
    """Describe a fader value: protocol 0..100 shown as 0.0..10.0."""
    return Cp750NumberDescription(
        key=key,
        parameter=parameter,
        translation_key=translation_key,
        native_min_value=0,
        native_max_value=FADER_MAX / 10,
        native_step=0.1,
        scale=10,
        mode=mode,
        entity_category=entity_category,
        entity_registry_enabled_default=enabled_default,
    )


NUMBERS: tuple[Cp750NumberDescription, ...] = (
    _fader("fader", KEY_FADER, "fader", mode=NumberMode.SLIDER),
    *(
        _fader(
            f"fader_preset_{suffix}",
            f"cp750.sys.fader_preset_{suffix}",
            f"fader_preset_{source}",
            mode=NumberMode.BOX,
            entity_category=EntityCategory.CONFIG,
            enabled_default=False,
        )
        for suffix, source in PRESET_INPUTS.items()
    ),
    *(
        Cp750NumberDescription(
            key=f"{source}_global_delay",
            parameter=f"cp750.sys.{source}_global_delay",
            translation_key=f"delay_{source}",
            native_min_value=0,
            native_max_value=DELAY_MAX,
            native_step=1,
            native_unit_of_measurement=UnitOfTime.MILLISECONDS,
            entity_category=EntityCategory.CONFIG,
            entity_registry_enabled_default=False,
            mode=NumberMode.BOX,
        )
        for source in INPUTS
    ),
    Cp750NumberDescription(
        key="surround_delay",
        parameter=KEY_SURROUND_DELAY,
        translation_key="surround_delay",
        native_min_value=0,
        native_max_value=SURROUND_DELAY_MAX,
        native_step=1,
        native_unit_of_measurement=UnitOfTime.MILLISECONDS,
        entity_category=EntityCategory.CONFIG,
        entity_registry_enabled_default=False,
        mode=NumberMode.BOX,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: Cp750ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the number entities."""
    coordinator = entry.runtime_data
    async_add_entities(Cp750Number(coordinator, description) for description in NUMBERS)


class Cp750Number(Cp750ProtocolEntity, NumberEntity):
    """A numeric CP750 setting."""

    entity_description: Cp750NumberDescription

    def __init__(self, coordinator: Cp750Coordinator, description: Cp750NumberDescription) -> None:
        """Initialize the number."""
        super().__init__(coordinator, description.key, description.parameter)
        self.entity_description = description

    @property
    def native_value(self) -> float | None:
        """Return the value in display units."""
        raw = self.raw_value
        if raw is None:
            return None
        try:
            value = int(raw)
        except ValueError:
            return None
        scale = self.entity_description.scale
        return value / scale if scale != 1 else value

    async def async_set_native_value(self, value: float) -> None:
        """Send a new value to the unit."""
        await self.coordinator.async_set(
            self.entity_description.parameter, round(value * self.entity_description.scale)
        )
