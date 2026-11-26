# Bringing in upstream changes

Anker eufy Integration is based on
[alaraun/homeassistant-eufy-home-security](https://github.com/alaraun/homeassistant-eufy-home-security).
Nothing comes across automatically: an upstream change is brought in only when chosen.
[CHANGES-FROM-UPSTREAM.md](../CHANGES-FROM-UPSTREAM.md) lists how this integration differs.

## One-off setup (per clone)

```bash
git remote add upstream https://github.com/alaraun/homeassistant-eufy-home-security.git
git remote set-url --push upstream DISABLED   # never push there by mistake
```

## Looking at what upstream changed

```bash
git fetch upstream
git log --oneline <last-synced-commit>..upstream/main
```

The last synced upstream commit is recorded in CHANGES-FROM-UPSTREAM.md.

## Bringing a change in

1. Work on a branch: `git switch -c sync/<topic> main`.
2. Pick the commits you want: `git cherry-pick <sha>...`. Upstream uses the domain
   `eufy_home_security` and the folder `custom_components/eufy_home_security`: rename
   those to `anker_eufy_integration` in what you bring in, and keep the card and event
   names from CHANGES-FROM-UPSTREAM.md.
3. Run the checks:

   ```bash
   ruff check && ruff format --check
   mypy custom_components tests
   pytest -q
   ```

4. Update the synced commit in CHANGES-FROM-UPSTREAM.md, open a pull request, and merge
   once CI passes.

## The library

The integration installs our own library, `anker-eufy-security` (import
`anker_eufy_security`, [source](https://github.com/abz2much/anker-eufy-security)), from
PyPI at the version pinned in `custom_components/anker_eufy_integration/manifest.json`.
It is based on alaraun's `eufy-home-security` under its own name, so it never shares an
installed copy with the upstream integration's library. Upstream code that imports
`eufy_home_security` must import `anker_eufy_security` when it comes in. For local
development, `uv sync` installs it editable from a sibling checkout at `../anker-eufy-security`
(`pyproject.toml`). That rewrites `uv.lock` locally: do not commit that change.
