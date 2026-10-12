"""Button entities for the Dolby CP750."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import Cp750ConfigEntry
from .const import INPUT_LAST, KEY_INPUT_MODE
from .coordinator import Cp750Coordinator
from .entity import Cp750ProtocolEntity

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: Cp750ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the button entities."""
    async_add_entities([Cp750PreviousInputButton(entry.runtime_data)])


class Cp750PreviousInputButton(Cp750ProtocolEntity, ButtonEntity):
    """Switch back to the input that was active before the current one."""

    _attr_translation_key = "previous_input"

    def __init__(self, coordinator: Cp750Coordinator) -> None:
        """Initialize the button."""
        super().__init__(coordinator, "previous_input", KEY_INPUT_MODE)

    async def async_press(self) -> None:
        """Send ``input_mode last``."""
        await self.coordinator.async_set(KEY_INPUT_MODE, INPUT_LAST)
