# Pulling upstream into this fork

The fork keeps alaraun's repository as the `upstream` remote. Fork changes are listed in
[CHANGES-FROM-UPSTREAM.md](../CHANGES-FROM-UPSTREAM.md).

## One-off setup (per clone)

```bash
git remote add upstream https://github.com/alaraun/homeassistant-eufy-home-security.git
git remote set-url --push upstream DISABLED   # never push to upstream by mistake
```

## Each upstream update

1. Fetch and look at what changed:

   ```bash
   git fetch upstream
   git log --oneline main..upstream/main
   ```

2. Merge on a branch, not on `main`:

   ```bash
   git switch -c sync/upstream-$(date +%Y-%m-%d) main
   git merge upstream/main
   ```

3. Conflicts happen only in the upstream files the fork touches (the table in
   CHANGES-FROM-UPSTREAM.md lists them). Keep upstream's version and re-apply the fork's
   small hook. The `fork_*.py` modules never conflict.

4. Check the fork still works against the new upstream:

   ```bash
   ruff check && ruff format --check
   mypy custom_components tests
   pytest -q
   ```

   Also re-read each fork change in the table: upstream may now do the same thing itself,
   in which case drop the fork change and its row.

5. Open a pull request from the sync branch and merge it once CI passes.

## The library

The integration installs `eufy-home-security` from PyPI at the version pinned in
`custom_components/eufy_home_security/manifest.json`. For local development, `uv sync`
installs it editable from a sibling checkout at `../python-eufy_home_security`
(`pyproject.toml`). That rewrites `uv.lock` locally: do not commit that change.
