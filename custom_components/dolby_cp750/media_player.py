"""Media player for the Dolby CP750: fader, mute and input in one entity."""

from __future__ import annotations

from homeassistant.components.media_player import (
    MediaPlayerDeviceClass,
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaPlayerState,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import Cp750ConfigEntry
from .const import (
    DOMAIN,
    FADER_MAX,
    INPUTS,
    KEY_FADER,
    KEY_INPUT_MODE,
    KEY_MUTE,
    SOURCE_NAMES,
)
from .coordinator import Cp750Coordinator
from .entity import Cp750Entity

PARALLEL_UPDATES = 1

SOURCE_LIST = [SOURCE_NAMES[value] for value in INPUTS]
_SOURCES_BY_NAME = {name: value for value, name in SOURCE_NAMES.items()}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: Cp750ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the media player."""
    async_add_entities([Cp750MediaPlayer(entry.runtime_data)])


class Cp750MediaPlayer(Cp750Entity, MediaPlayerEntity):
    """The CP750 as a media player.

    Volume maps the fader (0.0 to 10.0) onto 0 to 1. The unit has no power
    command, so the player is "on" while the unit answers and "off" otherwise.
    """

    _attr_name = None
    _attr_translation_key = "processor"
    _attr_device_class = MediaPlayerDeviceClass.RECEIVER
    _attr_supported_features = (
        MediaPlayerEntityFeature.VOLUME_SET
        | MediaPlayerEntityFeature.VOLUME_MUTE
        | MediaPlayerEntityFeature.VOLUME_STEP
        | MediaPlayerEntityFeature.SELECT_SOURCE
    )
    _attr_source_list = SOURCE_LIST
    # One step is 0.1 on the CP750 fader.
    _attr_volume_step = 1 / FADER_MAX

    def __init__(self, coordinator: Cp750Coordinator) -> None:
        """Initialize the media player.

        Unlike the other entities it stays available while the unit is
        unreachable, so a unit that is switched off shows as off.
        """
        super().__init__(coordinator, "media_player")

    @property
    def state(self) -> MediaPlayerState:
        """Return on while the unit answers."""
        return MediaPlayerState.ON if self.coordinator.data.reachable else MediaPlayerState.OFF

    @property
    def volume_level(self) -> float | None:
        """Return the fader as 0..1."""
        if not self.coordinator.data.reachable:
            return None
        try:
            return int(self.coordinator.data.values[KEY_FADER]) / FADER_MAX
        except (KeyError, ValueError):
            return None

    @property
    def is_volume_muted(self) -> bool | None:
        """Return True when the unit is muted."""
        if not self.coordinator.data.reachable:
            return None
        value = self.coordinator.data.values.get(KEY_MUTE)
        return None if value is None else value == "1"

    @property
    def source(self) -> str | None:
        """Return the active input."""
        if not self.coordinator.data.reachable:
            return None
        return SOURCE_NAMES.get(self.coordinator.data.values.get(KEY_INPUT_MODE, ""))

    async def async_set_volume_level(self, volume: float) -> None:
        """Set the fader."""
        await self.coordinator.async_set(KEY_FADER, round(volume * FADER_MAX))

    async def async_volume_up(self) -> None:
        """Raise the fader by 0.1."""
        await self.coordinator.async_step_fader(1)

    async def async_volume_down(self) -> None:
        """Lower the fader by 0.1."""
        await self.coordinator.async_step_fader(-1)

    async def async_mute_volume(self, mute: bool) -> None:
        """Mute or unmute."""
        await self.coordinator.async_set(KEY_MUTE, 1 if mute else 0)

    async def async_select_source(self, source: str) -> None:
        """Select an input by its display name."""
        value = _SOURCES_BY_NAME.get(source)
        if value is None:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="invalid_source",
                translation_placeholders={
                    "source": source,
                    "sources": ", ".join(SOURCE_LIST),
                },
            )
        await self.coordinator.async_set(KEY_INPUT_MODE, value)
