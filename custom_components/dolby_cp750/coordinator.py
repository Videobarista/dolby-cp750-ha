"""Data update coordinator for the Dolby CP750 integration."""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
import logging
from typing import TYPE_CHECKING, Any

from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .api import (
    Cp750Client,
    Cp750ConnectionError,
    Cp750Error,
    Cp750Identity,
    Cp750TimeoutError,
)
from .const import (
    CONF_SCAN_INTERVAL,
    CONF_SERIAL,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    FADER_MAX,
    FAST_KEYS,
    KEY_FADER,
    KEY_INPUT_MODE,
    KEY_MUTE,
    MANUFACTURER,
    MAX_MISSES,
    MODEL,
    OID_SYS_UPTIME,
    SLOW_POLL_INTERVAL,
    SNMP_STATUS_OIDS,
)
from .snmp import NoValue, SnmpClient, SnmpError, TimeTicks, as_text

if TYPE_CHECKING:
    from . import Cp750ConfigEntry

_LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class Cp750Data:
    """Snapshot of everything the entities show."""

    reachable: bool = False
    # Protocol parameter (lower case) -> value as reported by the unit.
    values: dict[str, str] = field(default_factory=dict)
    snmp_ok: bool = False
    # OID -> int or str; None when the agent does not have the object.
    snmp: dict[str, int | str | None] = field(default_factory=dict)
    boot_time: datetime | None = None
    # Parameters the unit did not answer; part of the data so that a change
    # makes the entities update.
    unsupported: frozenset[str] = frozenset()


class Cp750Coordinator(DataUpdateCoordinator[Cp750Data]):
    """Poll one CP750 over its ASCII protocol and, optionally, SNMP.

    A unit that is switched off is normal in a projection booth: the poll then
    succeeds with ``reachable=False`` so the entities show the unit as off
    instead of the integration failing. That is logged at debug level only.
    """

    config_entry: Cp750ConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: Cp750ConfigEntry,
        client: Cp750Client,
        snmp_client: SnmpClient | None,
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=timedelta(
                seconds=entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
            ),
            always_update=False,
        )
        self.client = client
        self.snmp_client = snmp_client
        self.identity: Cp750Identity | None = None
        self.unsupported: set[str] = set()
        self._keys: Counter[str] = Counter()
        self._misses: dict[str, int] = {}
        self._slow_due = 0.0
        self._identified_connection = 0
        self._wrong_device = False
        self._was_reachable: bool | None = None
        self._snmp_was_ok: bool | None = None
        self.device_info = self._build_device_info()

    @property
    def unique_base(self) -> str:
        """Return the prefix for unique IDs and the device identifier."""
        return self.config_entry.unique_id or self.config_entry.entry_id

    @property
    def registered_keys(self) -> list[str]:
        """Return the protocol parameters entities currently ask for."""
        return sorted(self._keys)

    def _build_device_info(self) -> DeviceInfo:
        identity = self.identity
        serial = (identity.serial if identity else None) or self.config_entry.data.get(CONF_SERIAL)
        return DeviceInfo(
            identifiers={(DOMAIN, self.unique_base)},
            manufacturer=MANUFACTURER,
            model=MODEL,
            name=self.config_entry.title,
            sw_version=identity.version if identity else None,
            serial_number=serial,
        )

    @callback
    def async_register_key(self, key: str) -> Callable[[], None]:
        """Poll ``key`` while the returned callback has not been called."""
        self._keys[key] += 1

        @callback
        def _unregister() -> None:
            self._keys[key] -= 1
            if self._keys[key] <= 0:
                del self._keys[key]

        return _unregister

    def is_supported(self, key: str) -> bool:
        """Return False for parameters the unit did not answer."""
        return key not in self.unsupported

    # ------------------------------------------------------------------
    # Setup and identification
    # ------------------------------------------------------------------

    async def _async_setup(self) -> None:
        """Identify the unit; an unreachable unit is not an error."""
        try:
            await self._async_identify()
        except Cp750Error as err:
            _LOGGER.debug(
                "CP750 at %s is not reachable during setup, it will show as off: %s",
                self.client.host,
                err,
            )
        if self._wrong_device:
            await self.client.disconnect()
            raise ConfigEntryError(
                translation_domain=DOMAIN,
                translation_key="wrong_device",
                translation_placeholders={"host": self.client.host},
            )

    async def _async_identify(self) -> None:
        """Read version and serial number once for every new connection."""
        await self.client.connect()
        if self._identified_connection == self.client.connection_count:
            return
        identity = await self.client.identify()
        self._identified_connection = self.client.connection_count

        expected = self.config_entry.data.get(CONF_SERIAL)
        if expected and identity.serial and identity.serial != expected:
            if not self._wrong_device:
                _LOGGER.error(
                    "The CP750 at %s has serial number %s, but this entry was set up for "
                    "serial number %s; it will not be controlled until the address is "
                    "corrected with Reconfigure",
                    self.client.host,
                    identity.serial,
                    expected,
                )
            self._wrong_device = True
            return
        self._wrong_device = False

        if identity != self.identity:
            self.identity = identity
            self.device_info = self._build_device_info()
            self._async_update_device_registry()

    @callback
    def _async_update_device_registry(self) -> None:
        """Store a changed firmware version or serial number on the device."""
        registry = dr.async_get(self.hass)
        identifier = (DOMAIN, self.unique_base)
        # Look the device up through the entry: identifiers are only unique per
        # config entry, and this works on every supported Home Assistant release.
        for device in dr.async_entries_for_config_entry(registry, self.config_entry.entry_id):
            if identifier in device.identifiers:
                registry.async_update_device(
                    device.id,
                    sw_version=self.device_info.get("sw_version"),
                    serial_number=self.device_info.get("serial_number"),
                )

    # ------------------------------------------------------------------
    # Polling
    # ------------------------------------------------------------------

    async def _async_update_data(self) -> Cp750Data:
        """Read the unit; an unreachable unit is reported, not raised."""
        previous = self.data
        values: dict[str, str] = dict(previous.values) if previous else {}
        boot_time = previous.boot_time if previous else None

        try:
            await self._async_identify()
            if self._wrong_device:
                raise Cp750ConnectionError("A different CP750 answers at this address")
            await self._async_poll(values)
        except Cp750Error as err:
            await self.client.disconnect()
            if self._was_reachable is not False:
                _LOGGER.debug(
                    "CP750 at %s is not responding, reporting it as off: %s",
                    self.client.host,
                    err,
                )
            self._was_reachable = False
            return Cp750Data(
                reachable=False,
                values=values,
                boot_time=boot_time,
                unsupported=frozenset(self.unsupported),
            )

        if self._was_reachable is False:
            _LOGGER.debug("CP750 at %s is responding again", self.client.host)
        self._was_reachable = True

        data = Cp750Data(
            reachable=True,
            values=values,
            boot_time=boot_time,
            unsupported=frozenset(self.unsupported),
        )
        if self.snmp_client is not None:
            await self._async_poll_snmp(data)
        return data

    async def _async_poll(self, values: dict[str, str]) -> None:
        """Read the fast parameters, and the slow ones when they are due."""
        # Every firmware answers the fader. No answer means the unit is gone.
        values[KEY_FADER] = await self.client.query(KEY_FADER)

        now = self.hass.loop.time()
        slow_keys = [
            key for key in self._keys if key not in FAST_KEYS and key not in self.unsupported
        ]
        keys = [key for key in FAST_KEYS if key != KEY_FADER and key not in self.unsupported]
        if now >= self._slow_due or any(key not in values for key in slow_keys):
            keys.extend(slow_keys)
            self._slow_due = now + SLOW_POLL_INTERVAL

        for key in keys:
            try:
                values[key] = await self.client.query(key)
            except Cp750TimeoutError:
                await self._async_handle_miss(key)
                continue
            self._misses.pop(key, None)

    async def _async_handle_miss(self, key: str) -> None:
        """Count a parameter that got no answer; give up on it after a few polls."""
        # Make sure the unit itself is still there; this raises when it is not.
        await self.client.query(KEY_FADER)
        misses = self._misses.get(key, 0) + 1
        if misses < MAX_MISSES:
            self._misses[key] = misses
            return
        self._misses.pop(key, None)
        self.unsupported.add(key)
        _LOGGER.warning(
            "The CP750 at %s does not answer %s; entities that use it are unavailable "
            "until the integration is reloaded",
            self.client.host,
            key,
        )

    async def _async_poll_snmp(self, data: Cp750Data) -> None:
        """Read the status objects of the CP750 MIB."""
        if self.snmp_client is None:
            return
        try:
            result = await self.snmp_client.get(SNMP_STATUS_OIDS)
        except SnmpError as err:
            if self._snmp_was_ok is not False:
                _LOGGER.warning(
                    "No SNMP status from %s, SNMP entities are unavailable: %s",
                    self.client.host,
                    err,
                )
            self._snmp_was_ok = False
            return
        if self._snmp_was_ok is False:
            _LOGGER.info("SNMP status from %s is available again", self.client.host)
        self._snmp_was_ok = True

        data.snmp_ok = True
        data.snmp = {oid: _plain(value) for oid, value in result.items()}
        data.boot_time = _boot_time(result.get(OID_SYS_UPTIME), data.boot_time)

    # ------------------------------------------------------------------
    # Commands
    # ------------------------------------------------------------------

    async def async_set(self, key: str, value: str | int) -> None:
        """Set a parameter and show the value the unit reports back.

        Pressing a control while the unit is switched off is normal operation,
        so failures are logged at debug level and the next poll shows the truth.
        """
        if self._wrong_device:
            _LOGGER.debug("Not sending %s to %s: a different CP750 answers there", key, value)
            return
        try:
            reported = {key: await self.client.set(key, value)}
            if key == KEY_INPUT_MODE:
                # A new input can bring its own fader preset.
                for extra in (KEY_FADER, KEY_MUTE):
                    reported[extra] = await self.client.query(extra)
        except Cp750Error as err:
            _LOGGER.debug("Could not set %s to %s on %s: %s", key, value, self.client.host, err)
            await self.async_request_refresh()
            return

        if reported[key] != str(value) and value != "last":
            _LOGGER.debug("The CP750 kept %s at %s instead of %s", key, reported[key], value)
        if self.data is None:
            return
        self.async_set_updated_data(
            replace(self.data, reachable=True, values={**self.data.values, **reported})
        )

    async def async_step_fader(self, delta: int) -> None:
        """Move the fader by ``delta`` steps of 0.1, starting from its current value."""
        try:
            current = int(await self.client.query(KEY_FADER))
        except (Cp750Error, ValueError) as err:
            _LOGGER.debug("Could not read the fader of %s: %s", self.client.host, err)
            return
        target = max(0, min(FADER_MAX, current + delta))
        if target != current:
            await self.async_set(KEY_FADER, target)

    async def async_send_raw(self, command: str) -> list[str]:
        """Send a raw command for the ``send_command`` action; errors are raised."""
        if self._wrong_device:
            raise Cp750ConnectionError("A different CP750 answers at this address")
        lines = await self.client.send_raw(command)
        await self.async_request_refresh()
        return lines


def _plain(value: Any) -> int | str | None:
    """Turn a decoded SNMP value into a plain int or str (None when missing)."""
    if isinstance(value, NoValue) or value is None:
        return None
    if isinstance(value, TimeTicks):
        return value.value
    if isinstance(value, bytes):
        return as_text(value)
    if isinstance(value, int | str):
        return value
    return str(value)


def _boot_time(uptime: Any, previous: datetime | None) -> datetime | None:
    """Derive the time of the last restart from sysUpTime, without jitter."""
    if not isinstance(uptime, TimeTicks):
        return previous
    boot = (dt_util.utcnow() - timedelta(seconds=uptime.value / 100)).replace(microsecond=0)
    if previous is not None and abs((boot - previous).total_seconds()) < 60:
        return previous
    return boot
