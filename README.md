<p align="center">
  <img src="https://raw.githubusercontent.com/abz2much/anker-eufy-integration/main/custom_components/anker_eufy_integration/brand/logo.png" alt="eufy" height="80">
</p>

# Anker eufy Integration for Home Assistant

[![Release](https://img.shields.io/github/v/release/abz2much/anker-eufy-integration)](https://github.com/abz2much/anker-eufy-integration/releases)
[![CI](https://github.com/abz2much/anker-eufy-integration/actions/workflows/ci.yml/badge.svg)](https://github.com/abz2much/anker-eufy-integration/actions/workflows/ci.yml)
[![License](https://img.shields.io/github/license/abz2much/anker-eufy-integration)](https://github.com/abz2much/anker-eufy-integration/blob/main/LICENSE)

Anker eufy Integration connects eufy Security HomeBases, cameras, doorbells and sensors
to Home Assistant. It talks to your devices over your own network wherever a device
allows it. It uses eufy's cloud only to sign in, to fetch the device list and keys, and
for the few things a device will not do locally.

It is based on [alaraun's eufy integration](https://github.com/alaraun/homeassistant-eufy-home-security)
(MIT) and has its own domain, `anker_eufy_integration`, so the two can be installed side
by side. Every change from that starting point is listed in
[CHANGES-FROM-UPSTREAM.md](CHANGES-FROM-UPSTREAM.md).

> [!WARNING]
> This is a beta. Only the devices listed in [Supported devices](docs/devices.md) have been
> tested, and a release may change entities or options. Keep the eufy app installed.
> This project is not affiliated with or endorsed by Anker or eufy.

## What it does

- Each HomeBase appears as an alarm panel that you can arm Home, Away or Night, with its
  siren, storage and event history.
- Cameras show stills and live video, and report motion, people, pets and vehicles.
- Each camera has a Last visitor sensor that shows the last person it recognised.
- The E340 doorbell can sound its siren, play eufy's quick replies, play your own sound
  files, and report packages that are delivered, taken or left too long.
- A HomeBase can be restarted from Home Assistant.
- Connected sensors for each HomeBase and each paired device, battery health on every
  camera that reports it, and firmware update entities that show the version eufy offers.
- Motion, entry and smoke sensors, locks and keypads appear with the readings the
  library supports.

The features added in this integration are described in [docs/features.md](docs/features.md).
Model-by-model support is in [docs/devices.md](docs/devices.md).

## Requirements

- Home Assistant 2026.11.0 or newer, with ffmpeg. Home Assistant OS and the official
  container already include it.
- Home Assistant on the same network as the HomeBase. Other set-ups are covered in
  [docs/network.md](docs/network.md).
- A eufy account for Home Assistant alone, shared from the owner's account. eufy allows
  one session per account, so a sign-in elsewhere with the same account ends Home
  Assistant's session.

## Installation

1. In Home Assistant, open **Settings → Marketplace**, choose **Custom repositories**,
   and add `https://github.com/abz2much/anker-eufy-integration` with the category
   **Integration**.
2. Find **Anker eufy Integration** in the Marketplace, download it, and restart Home
   Assistant.

## Setup

1. Open **Settings → Devices & services → Add integration** and choose **Anker eufy
   Integration**.
2. Enter the eufy account's e-mail address and password. The session is kept, so a
   restart does not sign in again.
3. Every HomeBase, its paired devices and every standalone camera appear as devices.

eufy allows only a few sign-ins per account each day, and Home Assistant never signs in
again by itself. If you add devices to the eufy account later, press **Refresh device
list** on the **eufy account** device.

## Documentation

| Page | What it covers |
|---|---|
| [Added features](docs/features.md) | restart, Night arm, last visitor, packages, doorbell siren, quick replies, playing sound files, Connected, battery health, firmware updates |
| [Usage](docs/usage.md) | options, the alarm panel, camera images, event history, live video, settings |
| [Camera card](docs/card.md) | the dashboard card for one or more cameras |
| [HomeBase card](docs/homebase-card.md) | the dashboard card for a HomeBase |
| [Supported devices](docs/devices.md) | tested models and how to report a new one |
| [Network and security](docs/network.md) | network set-up, accounts and stored data |
| [Troubleshooting](docs/troubleshooting.md) | debug logging, diagnostics and known limits |
| [Bringing in upstream changes](docs/upstream-sync.md) | how changes from alaraun's integration are chosen and applied |

Report bugs and ideas as [issues](https://github.com/abz2much/anker-eufy-integration/issues),
with the integration's diagnostics download attached.

## Licence

This project is released under the [MIT licence](LICENSE), which keeps the copyright
notice of the integration it is based on. eufy and Anker are trademarks of Anker
Innovations.
