# Changes from upstream

This fork of [alaraun/homeassistant-eufy-home-security](https://github.com/alaraun/homeassistant-eufy-home-security)
adds features on top of upstream. Each change is kept small and, where possible, in its
own `fork_*.py` module, so upstream updates merge cleanly. See
[docs/fork-upstream-sync.md](docs/fork-upstream-sync.md) for how to pull upstream.

Forked from upstream commit `2a76edf` (release 0.4.21).

## Version

The manifest version is upstream's version plus `+fork.N` (SemVer build metadata), for
example `0.4.21+fork.1`, so Home Assistant shows which build is installed. Home
Assistant's loader and the Marketplace both accept this form. Bump `N` with each fork
change; reset it to `1` after merging a new upstream version. Do not merge the fork's
release-please PR: it would overwrite this version.

| Change | Files | Path | Source | Licence |
|---|---|---|---|---|
| HomeBase **Restart** button: disabled by default, under Configuration, only on stations the library can restart. Calls the library's `Station.async_restart` (command 1034). A session ended by another client shows upstream's Repairs message. | `fork_restart.py` (new), `button.py` (setup hook, 6 lines), `manifest.json` (version), `strings.json` and `translations/en.json` (button name, 3 error messages), `tests/test_restart_button.py` (new), `tests/test_packaging.py` (release-version check accepts `+fork.N`), `tests/test_fork_version.py` (new) | Local P2P | Own code; uses the upstream library's existing restart | MIT (this repo) |
