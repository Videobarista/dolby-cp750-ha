# Dolby CP750 for Home Assistant

[![Hassfest](https://github.com/Videobarista/dolby-cp750-ha/actions/workflows/hassfest.yml/badge.svg?branch=main)](https://github.com/Videobarista/dolby-cp750-ha/actions/workflows/hassfest.yml)
[![HACS validation](https://github.com/Videobarista/dolby-cp750-ha/actions/workflows/hacs.yml/badge.svg?branch=main)](https://github.com/Videobarista/dolby-cp750-ha/actions/workflows/hacs.yml)
[![CodeQL](https://github.com/Videobarista/dolby-cp750-ha/actions/workflows/codeql.yml/badge.svg?branch=main)](https://github.com/Videobarista/dolby-cp750-ha/actions/workflows/codeql.yml)
[![Ruff](https://github.com/Videobarista/dolby-cp750-ha/actions/workflows/ruff.yml/badge.svg?branch=main)](https://github.com/Videobarista/dolby-cp750-ha/actions/workflows/ruff.yml)
[![Tests](https://github.com/Videobarista/dolby-cp750-ha/actions/workflows/tests.yml/badge.svg?branch=main)](https://github.com/Videobarista/dolby-cp750-ha/actions/workflows/tests.yml)

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=Videobarista&repository=dolby-cp750-ha&category=integration)

[![HACS custom](https://img.shields.io/badge/HACS-custom-41BDF5.svg)](https://hacs.xyz/docs/faq/custom_repositories)
[![Quality scale: Bronze (aligned)](https://img.shields.io/badge/quality%20scale-bronze%20(aligned)-cd7f32.svg)](https://developers.home-assistant.io/docs/core/integration-quality-scale/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Code style: Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![Release](https://img.shields.io/github/v/release/Videobarista/dolby-cp750-ha?display_name=tag)](https://github.com/Videobarista/dolby-cp750-ha/releases)

> **Note:** this is version 1.0.0, built from the Dolby documentation; it still has to be tested on a real CP750.

Control a **Dolby CP750** digital cinema processor from Home Assistant: fader, mute,
input selection, decode modes and fader presets over the CP750's ASCII control
protocol, plus signal status, bitstream format, output relays and meters over SNMP.

## Entities

| Entity | Type | Description |
| --- | --- | --- |
| *(device name)* | Media player | Fader as volume, mute, input as source. Shows **off** while the unit does not answer. |
| Fader | Number | 0.0 to 10.0 in steps of 0.1, the scale of the front panel (7.0 is reference level) |
| Mute | Switch | |
| Input | Select | Digital 1–4, Analog, Non-sync, Microphone |
| Previous input | Button | Switches back to the input that was active before (`input_mode last`) |
| Power-on input | Select (config) | Input after power-up, or last used |
| PCM decode mode Digital 1 | Select (config) | Auto, Discrete (5.1), Dolby Surround 7.1, Pro Logic, Pro Logic II, Surround EX |
| Connection | Binary sensor (diagnostic) | On while the unit answers on its control port |

Disabled by default (enable them under the device when you need them):

| Entity | Type | Description |
| --- | --- | --- |
| PCM decode mode Digital 2–4, Analog | Select (config) | As above, for the other inputs |
| Dolby Digital decode mode Digital 1–4 | Select (config) | Two-channel decode mode for Dolby Digital bitstreams |
| Non-sync format | Select (config) | Format 60, 61, 70, 71, 73, 74 or 75 |
| Fader preset *input* | Number (config) | Fader level an input starts at, per input |
| Fader preset *input* enabled | Switch (config) | Whether that preset is used |
| Delay *input* | Number (config) | Global delay per input, 0–170 ms |
| Surround delay | Number (config) | 0–150 ms |

With SNMP enabled (the default):

| Entity | Type | Description |
| --- | --- | --- |
| Digital 1–4 signal | Sensor (enum) | Valid, invalid or not available (`cp750DigitalInputValid1-4`) |
| Bitstream format | Sensor (enum) | PCM, Dolby Digital, Dolby E or not available |
| Active decode mode | Sensor (enum) | Decode mode on the current signal path |
| Output relays | Binary sensor | On while the output relays are engaged |
| Last restart | Sensor (timestamp, diagnostic) | Derived from the SNMP agent's uptime |
| Meter L, C, R, LFE, Ls, Rs, Le, Re | Sensor (disabled by default) | Meter reading per channel, 0–60 according to the MIB |

The device shows the firmware version and serial number of the unit.

## How it works

- **Control** uses the ASCII protocol on TCP port **61408** (CP750 manual, section 7.2).
  The integration keeps one connection open, because the CP750 allows 20 TCP sessions and
  drops the oldest one when a 21st connects. Fader, mute and input are read every 5 seconds
  (adjustable); settings such as presets, delays and decode modes are read once a minute.
  Only the settings of enabled entities are read.
- **Status** comes from the CP750 SNMP agent (UDP port 161, community `public` by default),
  using the objects of `DOLBY-CP750-MIB`. SNMP v2c is tried first, then v1.
- **Switched off is normal.** A unit that does not answer is shown as off and is picked up
  again as soon as it answers; this is logged at debug level only. The CP750 has no power
  command, so the integration cannot switch it on or off. Use a switched outlet for that.
- If a parameter does not answer twice in a row (older firmware), the entities that use it
  become unavailable and one warning is logged.

## Actions

### `dolby_cp750.send_command`

Sends one line of the ASCII protocol and returns the reply lines. Use it to test commands,
or for settings that have no entity.

```yaml
action: dolby_cp750.send_command
data:
  config_entry_id: 0123456789abcdef0123456789abcdef
  command: cp750.sys.fader ?
response_variable: reply
```

`reply.lines` then holds for example `["cp750.sys.fader 70"]`. `status` returns every
parameter, `help` the command list. The integration refreshes its state after the command.

### Example: Dolby Surround 7.1 for a feature

```yaml
action: select.select_option
target:
  entity_id: select.dolby_cp750_pcm_decode_mode_digital_1
data:
  option: 4_discrete_sur
```

## Installation

### HACS (custom repository)

1. Open HACS, open the menu (three dots) and choose **Custom repositories**.
2. Add `https://github.com/Videobarista/dolby-cp750-ha` with category **Integration**.
3. Install **Dolby CP750** and restart Home Assistant.

Or use the "Open in HACS" button above.

### Manual

Copy `custom_components/dolby_cp750` to the `custom_components` folder of your Home
Assistant configuration and restart.

## Configuration

**Settings → Devices & services → Add integration → Dolby CP750**

| Field | Description |
| --- | --- |
| Host | IP address or host name of the CP750 (factory default `192.168.1.136`) |
| Port | 61408 |
| Use SNMP | Read signal status, bitstream format, decode mode, relays and meters |
| SNMP community | Read community, usually `public` |

The unit must be switched on and reachable while you add it. Use **Reconfigure** on the
integration entry to change the address or the SNMP settings later.

**Options:** the polling interval for fader, mute and input (2–60 seconds, default 5).

## Known limitations

- The SNMP object IDs come from `DOLBY-CP750-MIB`, combined with Dolby's enterprise number
  6729 and `DOLBY-PRODUCTS-MIB` (`cp750Root` is `1.3.6.1.4.1.6729.2.1.1.1.2`). The
  diagnostics download contains an SNMP walk of the Dolby subtree, which shows what a unit
  really reports.
- The MIB does not say in which unit the meters are; they are shown as plain numbers.
- Dolby's release notes for firmware 1.2.8.3 mention that switching to Non-sync while it is
  set to format 71 (Mono C) can distort the audio until the CP750 is restarted.
- The CP750 does not push changes, so a change made on the front panel shows up at the next
  poll.

## Removal

1. Go to **Settings → Devices & services** and open **Dolby CP750**.
2. Open the menu (three dots) next to the entry and choose **Delete**.
3. To remove the files as well: in HACS, open **Dolby CP750** and choose **Remove**, or
   delete `custom_components/dolby_cp750` for a manual installation. Restart Home Assistant
   afterwards.

Nothing is changed on the CP750 itself.

## Quality scale

This integration is aligned with the **Bronze** tier of the
[Home Assistant integration quality scale](https://developers.home-assistant.io/docs/core/integration-quality-scale/).
Home Assistant only grades integrations that ship with Home Assistant itself, so this is a
self-assessment, not an official rating. The status per rule is recorded in
[`quality_scale.yaml`](custom_components/dolby_cp750/quality_scale.yaml).

## Development

The tests use [pytest-homeassistant-custom-component](https://github.com/MatthewFlamm/pytest-homeassistant-custom-component)
and run on every push. They talk to an in-memory CP750 and SNMP agent that follow the
manual and the MIB. To run them locally (Python 3.14):

```bash
pip install -r requirements_test.txt
pytest --cov --cov-report=term-missing
```

## Credits

- Protocol: *Dolby CP750 Digital Cinema Processor Manual*, section 7.2 (ASCII control) and
  the `DOLBY-CP750-MIB`.
- Real-world behaviour of the ASCII protocol (line endings, `status` output, session limit)
  was checked against [cp750-java](https://github.com/Cybso/cp750-java) by Roland Tapken,
  the library behind the openHAB DolbyCP binding.

The icon and logo are generic drawings made for this project; they are not Dolby logos.
Dolby is a trademark of Dolby Laboratories. This project is not affiliated with or endorsed
by Dolby Laboratories.

## License

[MIT](LICENSE)
