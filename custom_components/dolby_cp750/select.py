"""Select entities for the Dolby CP750: input, power-on input, formats, decode modes."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import Cp750ConfigEntry
from .const import (
    DECODE_MODES,
    INPUT_LAST,
    INPUTS,
    KEY_INPUT_MODE,
    KEY_NON_SYNC_FORMAT,
    KEY_POWER_ON_INPUT,
    NON_SYNC_FORMATS,
)
from .coordinator import Cp750Coordinator
from .entity import Cp750ProtocolEntity

PARALLEL_UPDATES = 1


@dataclass(frozen=True, kw_only=True)
class Cp750SelectDescription(SelectEntityDescription):
    """Describes a select backed by a protocol parameter."""

    parameter: str


# (protocol suffix, translation suffix) of the inputs that have a decode mode
_PCM_DECODE = (("1", "dig_1"), ("2", "dig_2"), ("3", "dig_3"), ("4", "dig_4"), ("a", "analog"))
_DOLBY_DIGITAL_DECODE = (("1", "dig_1"), ("2", "dig_2"), ("3", "dig_3"), ("4", "dig_4"))

SELECTS: tuple[Cp750SelectDescription, ...] = (
    Cp750SelectDescription(
        key="input",
        parameter=KEY_INPUT_MODE,
        translation_key="input",
        options=list(INPUTS),
    ),
    Cp750SelectDescription(
        key="power_on_input",
        parameter=KEY_POWER_ON_INPUT,
        translation_key="power_on_input",
        options=[*INPUTS, INPUT_LAST],
        entity_category=EntityCategory.CONFIG,
    ),
    Cp750SelectDescription(
        key="non_sync_format",
        parameter=KEY_NON_SYNC_FORMAT,
        translation_key="non_sync_format",
        options=list(NON_SYNC_FORMATS),
        entity_category=EntityCategory.CONFIG,
        entity_registry_enabled_default=False,
    ),
    *(
        Cp750SelectDescription(
            key=f"pcm_decode_mode_{suffix}",
            parameter=f"cp750.sys.pcm_2_channel_decode_mode_{suffix}",
            translation_key=f"pcm_decode_mode_{source}",
            options=list(DECODE_MODES),
            entity_category=EntityCategory.CONFIG,
            # Digital 1 (the cinema server) is where 5.1 / 7.1 switching happens.
            entity_registry_enabled_default=suffix == "1",
        )
        for suffix, source in _PCM_DECODE
    ),
    *(
        Cp750SelectDescription(
            key=f"dolby_digital_decode_mode_{suffix}",
            parameter=f"cp750.sys.dolby_digital_2_channel_decode_mode_{suffix}",
            translation_key=f"dolby_digital_decode_mode_{source}",
            options=list(DECODE_MODES),
            entity_category=EntityCategory.CONFIG,
            entity_registry_enabled_default=False,
        )
        for suffix, source in _DOLBY_DIGITAL_DECODE
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: Cp750ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the select entities."""
    coordinator = entry.runtime_data
    async_add_entities(Cp750Select(coordinator, description) for description in SELECTS)


class Cp750Select(Cp750ProtocolEntity, SelectEntity):
    """A CP750 setting with a fixed set of values."""

    entity_description: Cp750SelectDescription

    def __init__(self, coordinator: Cp750Coordinator, description: Cp750SelectDescription) -> None:
        """Initialize the select."""
        super().__init__(coordinator, description.key, description.parameter)
        self.entity_description = description

    @property
    def current_option(self) -> str | None:
        """Return the current value; states such as n_a show as unknown."""
        raw = self.raw_value
        if raw is None:
            return None
        value = raw.lower()
        return value if value in (self.entity_description.options or ()) else None

    async def async_select_option(self, option: str) -> None:
        """Send the chosen value to the unit."""
        await self.coordinator.async_set(self.entity_description.parameter, option)
