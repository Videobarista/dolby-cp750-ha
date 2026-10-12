"""Config flow for the Dolby CP750 integration."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
)

from .api import Cp750Client, Cp750ConnectionError, Cp750Identity, Cp750TimeoutError
from .const import (
    CONF_SCAN_INTERVAL,
    CONF_SERIAL,
    CONF_SNMP_COMMUNITY,
    CONF_SNMP_ENABLED,
    CONF_SNMP_VERSION,
    DEFAULT_NAME,
    DEFAULT_PORT,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_SNMP_COMMUNITY,
    DOMAIN,
    MAX_SCAN_INTERVAL,
    MIN_SCAN_INTERVAL,
    OID_SYS_DESCR,
    SNMP_PORT,
)
from .snmp import SNMP_V1, SNMP_V2C, VERSION_NAMES, SnmpClient, SnmpError

_LOGGER = logging.getLogger(__name__)

USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Required(CONF_PORT, default=DEFAULT_PORT): cv.port,
        vol.Required(CONF_SNMP_ENABLED, default=True): bool,
        vol.Optional(CONF_SNMP_COMMUNITY, default=DEFAULT_SNMP_COMMUNITY): str,
    }
)

OPTIONS_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL): NumberSelector(
            NumberSelectorConfig(
                min=MIN_SCAN_INTERVAL,
                max=MAX_SCAN_INTERVAL,
                step=1,
                unit_of_measurement="s",
                mode=NumberSelectorMode.BOX,
            )
        ),
    }
)


class CannotConnect(Exception):
    """Nothing answers on the control port."""


class NotCp750(Exception):
    """Something answers, but not like a CP750."""


class SnmpFailed(Exception):
    """The SNMP agent does not answer."""


@dataclass(frozen=True, slots=True)
class _Unit:
    """What validation found out about a unit."""

    host: str
    port: int
    identity: Cp750Identity
    snmp_version: str | None

    @property
    def unique_id(self) -> str:
        """Key entries by serial number; fall back to the address."""
        return self.identity.serial or self.host.lower()


async def _async_probe_snmp(host: str, community: str) -> str:
    """Return the SNMP version ("2c" or "1") the agent answers to."""
    for version in (SNMP_V2C, SNMP_V1):
        client = SnmpClient(host, community, version=version, port=SNMP_PORT)
        try:
            await client.get([OID_SYS_DESCR])
        except SnmpError as err:
            _LOGGER.debug("No SNMPv%s answer from %s: %s", VERSION_NAMES[version], host, err)
            continue
        return VERSION_NAMES[version]
    raise SnmpFailed


async def _async_validate(data: Mapping[str, Any]) -> _Unit:
    """Connect to the unit, identify it and check SNMP when enabled."""
    host = data[CONF_HOST]
    port = data[CONF_PORT]
    client = Cp750Client(host, port)
    try:
        identity = await client.identify()
    except Cp750ConnectionError as err:
        raise CannotConnect from err
    except Cp750TimeoutError as err:
        raise NotCp750 from err
    finally:
        await client.disconnect()

    snmp_version: str | None = None
    if data.get(CONF_SNMP_ENABLED):
        snmp_version = await _async_probe_snmp(
            host, data.get(CONF_SNMP_COMMUNITY) or DEFAULT_SNMP_COMMUNITY
        )
    return _Unit(host=host, port=port, identity=identity, snmp_version=snmp_version)


def _entry_data(user_input: Mapping[str, Any], unit: _Unit) -> dict[str, Any]:
    """Build the config entry data."""
    snmp_enabled = bool(user_input.get(CONF_SNMP_ENABLED))
    return {
        CONF_HOST: unit.host,
        CONF_PORT: unit.port,
        CONF_SERIAL: unit.identity.serial,
        CONF_SNMP_ENABLED: snmp_enabled,
        CONF_SNMP_COMMUNITY: user_input.get(CONF_SNMP_COMMUNITY) or DEFAULT_SNMP_COMMUNITY,
        CONF_SNMP_VERSION: unit.snmp_version,
    }


class Cp750ConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for a Dolby CP750."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> Cp750OptionsFlow:
        """Return the options flow."""
        return Cp750OptionsFlow()

    async def _async_try(self, user_input: dict[str, Any], errors: dict[str, str]) -> _Unit | None:
        """Validate the input; fill ``errors`` and return None on failure."""
        try:
            return await _async_validate(user_input)
        except CannotConnect:
            errors["base"] = "cannot_connect"
        except NotCp750:
            errors["base"] = "not_cp750"
        except SnmpFailed:
            errors["base"] = "snmp_cannot_connect"
        except Exception:
            _LOGGER.exception("Unexpected error while validating the CP750")
            errors["base"] = "unknown"
        return None

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Handle manual setup."""
        errors: dict[str, str] = {}
        if user_input is not None:
            user_input = {**user_input, CONF_HOST: user_input[CONF_HOST].strip()}
            unit = await self._async_try(user_input, errors)
            if unit is not None:
                await self.async_set_unique_id(unit.unique_id)
                self._abort_if_unique_id_configured(
                    updates={CONF_HOST: unit.host, CONF_PORT: unit.port}
                )
                return self.async_create_entry(
                    title=DEFAULT_NAME, data=_entry_data(user_input, unit)
                )

        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(USER_SCHEMA, user_input),
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Change the address or SNMP settings of an existing entry."""
        errors: dict[str, str] = {}
        entry = self._get_reconfigure_entry()
        if user_input is not None:
            user_input = {**user_input, CONF_HOST: user_input[CONF_HOST].strip()}
            unit = await self._async_try(user_input, errors)
            if unit is not None:
                data = _entry_data(user_input, unit)
                if entry.data.get(CONF_SERIAL):
                    await self.async_set_unique_id(unit.unique_id)
                    self._abort_if_unique_id_mismatch(reason="wrong_device")
                    return self.async_update_reload_and_abort(entry, data_updates=data)
                # Entry of a unit without a serial number: it is keyed by address.
                return self.async_update_reload_and_abort(
                    entry, unique_id=unit.unique_id, data_updates=data
                )

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(
                USER_SCHEMA, user_input or dict(entry.data)
            ),
            errors=errors,
        )


class Cp750OptionsFlow(OptionsFlow):
    """Options: the polling interval."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Show and save the options."""
        if user_input is not None:
            return self.async_create_entry(
                data={CONF_SCAN_INTERVAL: int(user_input[CONF_SCAN_INTERVAL])}
            )
        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(
                OPTIONS_SCHEMA, self.config_entry.options
            ),
        )
