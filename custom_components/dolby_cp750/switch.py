"""Switch entities for the Dolby CP750: mute and fader preset enables."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import Cp750ConfigEntry
from .const import KEY_MUTE, PRESET_INPUTS
from .coordinator import Cp750Coordinator
from .entity import Cp750ProtocolEntity

PARALLEL_UPDATES = 1


@dataclass(frozen=True, kw_only=True)
class Cp750SwitchDescription(SwitchEntityDescription):
    """Describes an on/off parameter (0 or 1)."""

    parameter: str


SWITCHES: tuple[Cp750SwitchDescription, ...] = (
    Cp750SwitchDescription(key="mute", parameter=KEY_MUTE, translation_key="mute"),
    *(
        Cp750SwitchDescription(
            key=f"fader_preset_{suffix}_enable",
            parameter=f"cp750.sys.fader_preset_{suffix}_enable",
            translation_key=f"fader_preset_{source}_enable",
            entity_category=EntityCategory.CONFIG,
            entity_registry_enabled_default=False,
        )
        for suffix, source in PRESET_INPUTS.items()
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: Cp750ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the switch entities."""
    coordinator = entry.runtime_data
    async_add_entities(Cp750Switch(coordinator, description) for description in SWITCHES)


class Cp750Switch(Cp750ProtocolEntity, SwitchEntity):
    """A CP750 parameter that is 0 or 1."""

    entity_description: Cp750SwitchDescription

    def __init__(self, coordinator: Cp750Coordinator, description: Cp750SwitchDescription) -> None:
        """Initialize the switch."""
        super().__init__(coordinator, description.key, description.parameter)
        self.entity_description = description

    @property
    def is_on(self) -> bool | None:
        """Return True when the parameter is 1."""
        raw = self.raw_value
        if raw not in ("0", "1"):
            return None
        return raw == "1"

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Set the parameter to 1."""
        await self.coordinator.async_set(self.entity_description.parameter, 1)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Set the parameter to 0."""
        await self.coordinator.async_set(self.entity_description.parameter, 0)
