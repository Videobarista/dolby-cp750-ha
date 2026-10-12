"""Constants for the Dolby CP750 integration."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "dolby_cp750"
MANUFACTURER: Final = "Dolby Laboratories"
MODEL: Final = "CP750"
DEFAULT_NAME: Final = "Dolby CP750"

# Connection settings.
DEFAULT_PORT: Final = 61408
CONF_SERIAL: Final = "serial"
CONF_SNMP_ENABLED: Final = "snmp_enabled"
CONF_SNMP_COMMUNITY: Final = "snmp_community"
CONF_SNMP_VERSION: Final = "snmp_version"
DEFAULT_SNMP_COMMUNITY: Final = "public"
SNMP_PORT: Final = 161

# Options.
CONF_SCAN_INTERVAL: Final = "scan_interval"
DEFAULT_SCAN_INTERVAL: Final = 5
MIN_SCAN_INTERVAL: Final = 2
MAX_SCAN_INTERVAL: Final = 60

# Settings that rarely change (presets, delays, decode modes) are read at this
# interval in seconds instead of on every poll.
SLOW_POLL_INTERVAL: Final = 60.0

# A parameter that does not answer this many polls in a row is treated as not
# supported by the firmware of the unit and is no longer asked for.
MAX_MISSES: Final = 2

# ---------------------------------------------------------------------------
# ASCII protocol parameters (Dolby CP750 manual, section 7.2, table 7-1).
# ---------------------------------------------------------------------------
KEY_VERSION: Final = "cp750.sysinfo.version"
KEY_SERIAL: Final = "cp750.sys.serial_number"
KEY_FADER: Final = "cp750.sys.fader"
KEY_MUTE: Final = "cp750.sys.mute"
KEY_INPUT_MODE: Final = "cp750.sys.input_mode"
KEY_POWER_ON_INPUT: Final = "cp750.sys.power_on_input"
KEY_NON_SYNC_FORMAT: Final = "cp750.sys.non_sync_format"
KEY_SURROUND_DELAY: Final = "cp750.sys.surround_delay"

# Read on every poll; everything else is read at SLOW_POLL_INTERVAL.
FAST_KEYS: Final = (KEY_FADER, KEY_MUTE, KEY_INPUT_MODE)

# Selectable inputs, in front-panel order. "last" is a command, not a state:
# it switches back to the previous input.
INPUTS: Final = ("dig_1", "dig_2", "dig_3", "dig_4", "analog", "non_sync", "mic")
INPUT_LAST: Final = "last"

# Names shown as media player sources.
SOURCE_NAMES: Final = {
    "dig_1": "Digital 1",
    "dig_2": "Digital 2",
    "dig_3": "Digital 3",
    "dig_4": "Digital 4",
    "analog": "Analog",
    "non_sync": "Non-sync",
    "mic": "Microphone",
}

# Suffixes the protocol uses for per-input settings (fader presets).
PRESET_INPUTS: Final = {
    "1": "dig_1",
    "2": "dig_2",
    "3": "dig_3",
    "4": "dig_4",
    "a": "analog",
    "m": "mic",
    "n": "non_sync",
}

# Two-channel decode modes that can be set. The unit can also report "n_a"
# and "invalid", which are states and not choices.
DECODE_MODES: Final = (
    "auto",
    "lr_discrete",
    "4_discrete_sur",
    "prologic",
    "prologic_2",
    "surround_ex",
)

NON_SYNC_FORMATS: Final = ("60", "61", "70", "71", "73", "74", "75")

FADER_MAX: Final = 100
DELAY_MAX: Final = 170
SURROUND_DELAY_MAX: Final = 150

# ---------------------------------------------------------------------------
# SNMP (DOLBY-CP750-MIB). The MIB places cp750Root at { cinemaProcessors 2 };
# cinemaProcessors is 1.3.6.1.4.1.6729.2.1.1.1 in DOLBY-PRODUCTS-MIB
# (enterprise 6729 is Dolby Laboratories).
# ---------------------------------------------------------------------------
OID_DOLBY_ENTERPRISE: Final = "1.3.6.1.4.1.6729"
OID_CP750_ROOT: Final = "1.3.6.1.4.1.6729.2.1.1.1.2"
_STATUS: Final = f"{OID_CP750_ROOT}.2"

OID_SERIAL: Final = f"{OID_CP750_ROOT}.1.1.0"
OID_DIGITAL_VALID: Final = {n: f"{_STATUS}.{n}.0" for n in (1, 2, 3, 4)}
OID_INPUT_SELECTION: Final = f"{_STATUS}.5.0"
OID_FADER_LEVEL: Final = f"{_STATUS}.6.0"
OID_BITSTREAM_FORMAT: Final = f"{_STATUS}.7.0"
OID_DECODE_MODE: Final = f"{_STATUS}.8.0"
OID_MUTE_STATUS: Final = f"{_STATUS}.9.0"
OID_RELAY_STATUS: Final = f"{_STATUS}.10.0"
OID_METER_LEVELS: Final = f"{_STATUS}.11.0"

# Standard MIB-2 system group, supported by the CP750 SNMP agent.
OID_SYS_DESCR: Final = "1.3.6.1.2.1.1.1.0"
OID_SYS_UPTIME: Final = "1.3.6.1.2.1.1.3.0"

SNMP_STATUS_OIDS: Final = (
    *OID_DIGITAL_VALID.values(),
    OID_INPUT_SELECTION,
    OID_FADER_LEVEL,
    OID_BITSTREAM_FORMAT,
    OID_DECODE_MODE,
    OID_MUTE_STATUS,
    OID_RELAY_STATUS,
    OID_METER_LEVELS,
    OID_SYS_UPTIME,
)

# Channel order of cp750MeterLevels: "L C R LFE Ls Rs Le Re".
METER_CHANNELS: Final = ("l", "c", "r", "lfe", "ls", "rs", "le", "re")

# cp750DigitalInputValidN
SIGNAL_STATES: Final = {0: "not_available", 1: "valid", 2: "invalid"}
# cp750BitstreamFormat
BITSTREAM_FORMATS: Final = ("pcm", "dolby_digital", "dolby_e", "not_available")
# cp750DecodeMode, plus the modes table 7-1 lists for the same setting.
ACTIVE_DECODE_MODES: Final = (*DECODE_MODES, "not_available", "invalid")
# cp750RelayStatus
RELAY_ENGAGED: Final = 1
RELAY_DISENGAGED: Final = 2
