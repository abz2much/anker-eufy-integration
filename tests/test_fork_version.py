"""Fork: the manifest version is upstream's release plus ``+fork.N``.

Upstream's packaging test requires manifest.json to carry release-please's version. The
fork adds only a ``+fork.N`` build suffix, so Home Assistant shows which build is
installed; any other difference must still be caught.
"""

from __future__ import annotations

from typing import Any, Final

import pytest
from test_packaging import _release_version_violations

_CONFIG: Final[dict[str, Any]] = {
    "packages": {
        ".": {
            "extra-files": [
                {
                    "type": "json",
                    "path": "custom_components/eufy_home_security/manifest.json",
                    "jsonpath": "$.version",
                }
            ],
            "include-component-in-tag": False,
        }
    }
}
_RELEASED: Final = {".": "0.4.21"}


def test_a_fork_build_of_the_released_version_matches() -> None:
    assert _release_version_violations("0.4.21+fork.1", _RELEASED, _CONFIG) == []


@pytest.mark.parametrize("version", ["0.4.22+fork.1", "0.4.21+other.1", "0.4.21+fork.x"])
def test_any_other_version_still_disagrees(version: str) -> None:
    assert _release_version_violations(version, _RELEASED, _CONFIG) == [
        f"manifest.json version {version!r} != release-please version '0.4.21'"
    ]
