# Changes from upstream

Anker eufy Integration is based on
[alaraun/homeassistant-eufy-home-security](https://github.com/alaraun/homeassistant-eufy-home-security)
(MIT; its copyright notice is kept in [LICENSE](LICENSE)), taken at upstream commit
`2a76edf` (release 0.4.21). It is a separate integration with its own domain and
versions: upstream changes are brought in only when chosen
([docs/upstream-sync.md](docs/upstream-sync.md)).

Last synced upstream commit: `2a76edf`.

| Change | Files | Path | Source | Licence |
|---|---|---|---|---|
| Own identity: domain `anker_eufy_integration`, name "Anker eufy Integration", cards `anker-eufy-camera-card` and `anker-eufy-homebase-card`, event `anker_eufy_integration_event`, stream view, media and cache folders, links and code owner. Version starts at `0.1.0`. | `custom_components/anker_eufy_integration/` (folder moved; `ruff.toml` keeps upstream's import order), `manifest.json`, `hacs.json`, `const.py`, `services.yaml`, `frontend/*.js` (renamed), `pyproject.toml`, `uv.lock`, `.release-please-manifest.json`, `README.md`, `SECURITY.md`, docs, tests (paths and names), `tests/test_identity.py` (new) | n/a | Own | MIT |
| HomeBase **Restart** button: disabled by default, under Configuration, only on stations the library can restart. Calls the library's `Station.async_restart` (command 1034). A session ended by another client shows the Repairs message. | `restart_button.py` (new), `button.py` (setup hook), `strings.json` and `translations/en.json` (button name, 3 error messages), `tests/test_restart_button.py` (new) | Local P2P | Own; uses the library's existing restart | MIT |
| **Last visitor** sensor per camera: the name of the last person the camera recognised, kept until it recognises someone else; `detected_at` attribute; restored after a restart. | `visitor_sensor.py` (new), `sensor.py` (setup hook), `strings.json` and `translations/en.json` (sensor name), `tests/test_visitor_sensor.py` (new) | Local P2P (cloud push when on) | Own; uses the library's `SecurityEvent.person_name` | MIT |
| **Night arm**: the alarm panel arms Night (Custom 1, guard mode 3) where the HomeBase has Custom 1 set up, and shows Custom 1 as `armed_night`; the arming event gains `armed_night`. Schedule, Custom 2 and 3 and geofencing stay custom bypass. | `alarm_control_panel.py` (supported features, `async_alarm_arm_night`), `detections.py` (state map, arming event types), `tests/test_night_arm.py` (new), `tests/test_alarm_control_panel.py` and `tests/test_event.py` (Custom 1 expectations) | Local P2P | Own; Custom 1 write is live-verified in the library (`capabilities.py`) | MIT |
| **Doorbell siren** (E340 / T8214): on for a duration of 1-30 s (default 10), off when it ends or is turned off. The eufy app offers this model no alarm button, so the library has no table entry; the command was proven on hardware: SET_DEVS_TONE_FILE (1202) with the seconds on the doorbell's channel, 0 to stop, sent with the library's legacy scalar sender. | `doorbell_siren.py` (new), `siren.py` (setup hook), `strings.json` and `translations/en.json` (duration message), `tests/test_doorbell_siren.py` (new) | Local P2P | Own; command values from bropat eufy-security-client `station.ts` triggerDeviceAlarmSound (MIT), confirmed on hardware 26 Nov 2026 | MIT |
| **Package sensors** on the doorbell: Package delivered, taken and stranded (event types 3301, 3302, 3304), each on for the detection hold. The library keeps these as a raw `event_type` without a detection; the sensors match the raw type from either source, and the router treats them as consumed for a doorbell (they no longer go to the fallback bus event there). | `package_sensors.py` (new), `binary_sensor.py` (setup hook), `detections.py` (package types, consumption rule), `strings.json` and `translations/en.json` (names), `tests/test_package_sensors.py` (new) | Local P2P if the HomeBase sends them (not yet seen), else cloud push | Own; event types from bropat eufy-security-client `src/push/types.ts` (MIT) | MIT |

The Python library (`eufy-home-security`, alaraun, MIT) is unchanged and installed from
PyPI at the version in `manifest.json`. Keep that version equal to the one the upstream
integration pins while both are installed in the same Home Assistant: they share one
copy of the library.
