# Security Policy

## Supported versions

Only the latest release receives fixes.

| Version | Supported |
| ------- | --------- |
| 1.0.x   | Yes       |

## Reporting a vulnerability

Please report security issues privately through GitHub:
**Security** tab of this repository → **Report a vulnerability**.
Do not open a public issue for security problems.

You can expect a first reply within a week.

## Deployment notes

- The CP750 ASCII control port (TCP 61408) has no authentication: anyone who can reach it
  can change the fader, mute and input. Keep the projection network separate from guest
  and office networks.
- SNMP v1/v2c sends the community string in clear text. The integration only reads; use a
  read-only community.
- The `dolby_cp750.send_command` action can send any protocol command, including network
  settings and a reboot. Only Home Assistant administrators may call it; automations and
  scripts can use it too, so keep that in mind when you write them.
- Diagnostics downloads redact the serial number and the SNMP community.
