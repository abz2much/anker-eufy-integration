"""The integration's own identity: Anker eufy Integration (``anker_eufy_integration``).

Every name another installed eufy integration could also claim is its own here: the
domain and folder, the display name, the card elements a browser registers once, the
URLs it serves and the event it fires. A clash with any of them would stop one of the
two integrations from loading or make their events and cards mix.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Final

from custom_components.anker_eufy_integration import card, const, recording_plays

_REPO_ROOT: Final = Path(__file__).resolve().parent.parent
_COMPONENT: Final = _REPO_ROOT / "custom_components" / "anker_eufy_integration"
_DOMAIN: Final = "anker_eufy_integration"


def _defined_elements() -> set[str]:
    names: set[str] = set()
    for script in (_COMPONENT / "frontend").glob("*.js"):
        names |= set(
            re.findall(r"customElements\.define\(\s*['\"]([a-z0-9-]+)['\"]", script.read_text())
        )
    return names


def test_the_manifest_names_the_integration() -> None:
    manifest = json.loads((_COMPONENT / "manifest.json").read_text())
    assert (manifest["domain"], manifest["name"]) == (_DOMAIN, "Anker eufy Integration")
    assert const.DOMAIN == _DOMAIN


def test_the_marketplace_lists_it_by_its_own_name() -> None:
    assert json.loads((_REPO_ROOT / "hacs.json").read_text())["name"] == "Anker eufy Integration"


def test_the_cards_register_their_own_elements() -> None:
    assert _defined_elements() == {
        "anker-eufy-camera-card",
        "anker-eufy-camera-card-editor",
        "anker-eufy-homebase-card",
        "anker-eufy-homebase-card-editor",
    }


def test_the_cards_are_served_under_the_domain() -> None:
    assert card.CARD_URL == "/anker_eufy_integration/anker-eufy-camera-card.js"
    assert card.HOMEBASE_CARD_URL == "/anker_eufy_integration/anker-eufy-homebase-card.js"
    assert recording_plays.RECORDING_URL.startswith("/api/anker_eufy_integration/")


def test_the_event_is_its_own() -> None:
    assert const.EVENT_EUFY_HOME_SECURITY == "anker_eufy_integration_event"


def test_the_cards_talk_to_this_integration() -> None:
    """The cards' websocket calls and media paths are built from their own DOMAIN."""
    for script in (_COMPONENT / "frontend").glob("*.js"):
        assert re.search(
            r"^const DOMAIN = 'anker_eufy_integration';$", script.read_text(), re.MULTILINE
        ), script.name
    camera = (_COMPONENT / "frontend" / "anker-eufy-camera-card.js").read_text()
    assert "media-source://media_source/local/anker_eufy_integration" in camera


def test_the_stream_view_name_is_its_own() -> None:
    assert const.STREAM_VIEW_NAME == "api:anker_eufy_integration:stream"


def test_action_pickers_offer_this_integrations_entities() -> None:
    services = (_COMPONENT / "services.yaml").read_text()
    integrations = set(re.findall(r"integration: (\S+)", services))
    assert integrations == {_DOMAIN}
