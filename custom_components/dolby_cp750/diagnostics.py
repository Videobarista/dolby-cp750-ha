"""Diagnostics for the Dolby CP750 integration.

Besides the polled state, a download also contains the raw output of the
``status`` command and an SNMP walk of the Dolby subtree. That shows what the
firmware of a unit really reports, which helps to support units the
integration was not tested with.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from . import Cp750ConfigEntry
from .api import Cp750Error
from .const import (
    CONF_SERIAL,
    CONF_SNMP_COMMUNITY,
    KEY_SERIAL,
    OID_DOLBY_ENTERPRISE,
    OID_SERIAL,
)
from .snmp import NoValue, SnmpError, TimeTicks, as_text

TO_REDACT = {CONF_SERIAL, CONF_SNMP_COMMUNITY, KEY_SERIAL, OID_SERIAL, "serial_number"}
REDACTED = "**REDACTED**"


def _json_value(oid: str, value: Any) -> Any:
    """Make a decoded SNMP value JSON friendly and hide the serial number."""
    if oid == OID_SERIAL:
        return REDACTED
    if isinstance(value, NoValue):
        return value.name
    if isinstance(value, TimeTicks):
        return value.value
    if isinstance(value, bytes):
        return as_text(value)
    return value


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: Cp750ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator = entry.runtime_data
    data = coordinator.data
    identity = coordinator.identity

    result: dict[str, Any] = {
        "entry": {
            "data": async_redact_data(dict(entry.data), TO_REDACT),
            "options": dict(entry.options),
        },
        "firmware": identity.version if identity else None,
        "reachable": data.reachable,
        "values": async_redact_data(dict(data.values), TO_REDACT),
        "registered_parameters": coordinator.registered_keys,
        "unsupported_parameters": sorted(coordinator.unsupported),
        "snmp": {
            "enabled": coordinator.snmp_client is not None,
            "ok": data.snmp_ok,
            "values": {oid: _json_value(oid, value) for oid, value in data.snmp.items()},
        },
    }

    if not data.reachable:
        return result

    try:
        lines = await coordinator.client.send_raw("status")
    except Cp750Error as err:
        result["status_command"] = f"failed: {err}"
    else:
        result["status_command"] = [
            REDACTED if "serial" in line.lower() else line for line in lines
        ]

    if coordinator.snmp_client is not None:
        try:
            rows = await coordinator.snmp_client.walk(OID_DOLBY_ENTERPRISE)
        except SnmpError as err:
            result["snmp_walk"] = f"failed: {err}"
        else:
            result["snmp_walk"] = {oid: _json_value(oid, value) for oid, value in rows}

    return result
