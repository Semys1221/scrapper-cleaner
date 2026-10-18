"""Niche presets for roofers, plumbers, and general renovation (France)."""

from __future__ import annotations

import pytest

from bootstrap.discovery import discover_presets
from bootstrap.validators import validate_preset_runtime
from config_loader import load_config
from query_planner import format_query
from shared.central_leads import PRESET_CATEGORY, category_for_preset
from taxonomy_gate import matches_taxonomy, taxonomy_excluded_keywords

TRADE_PRESETS = {
    "couvreurs": {
        "category": "COUVREUR",
        "keywords": [
            "couvreur",
            "couverture",
            "toiture",
            "zinguerie",
            "charpente-couverture",
        ],
        "accept": {
            "type": "Couvreur",
            "category": "Roofing contractor",
            "subtypes": "Zinguerie, charpente-couverture",
        },
        "reject": {
            "type": "Magasin de matériaux",
            "category": "Building materials store",
            "subtypes": "Toiture",
        },
    },
    "plombiers": {
        "category": "PLOMBIER",
        "keywords": [
            "plombier",
            "plomberie",
            "chauffagiste-plombier",
            "dépannage plomberie",
            "sanitaire",
        ],
        "accept": {
            "type": "Plombier",
            "category": "Plombier chauffagiste",
            "subtypes": "Dépannage plomberie, sanitaire",
        },
        "reject": {
            "type": "Showroom sanitaire",
            "category": "Magasin de salles de bain",
            "subtypes": "Sanitaire",
        },
    },
    "renovation": {
        "category": "RENOVATION",
        "keywords": [
            "entreprise de rénovation",
            "rénovation intérieure",
            "rénovation maison",
            "tous corps d'état",
            "entreprise générale du bâtiment",
        ],
        "accept": {
            "type": "Entreprise générale du bâtiment",
            "category": "Entreprise de rénovation",
            "subtypes": "Tous corps d'état, plombier, couvreur",
        },
        "reject": {
            "type": "Agence immobilière",
            "category": "Real estate agency",
            "subtypes": "Rénovation",
        },
    },
}

_SHARED_WITH_PAYSAGISTES = (
    "OUTSCRAPER_FILTERS",
    "OUTSCRAPER_BATCH_SIZE",
    "OUTSCRAPER_CONCURRENCY",
    "OUTSCRAPER_LIMIT_PER_QUERY",
    "OUTSCRAPER_POLL_INITIAL_S",
    "OUTSCRAPER_POLL_INTERVAL_S",
    "OUTSCRAPER_POLL_SLOW_S",
    "OUTSCRAPER_POLL_TIMEOUT_S",
    "OUTSCRAPER_TOTAL_LIMIT_BUFFER",
    "OUTSCRAPER_ENRICHMENT",
    "OUTSCRAPER_EMAIL_RECOVERY_ENABLED",
    "WEBSITE_REQUIRED",
    "TAXONOMY_GATE_ENABLED",
    "TAXONOMY_MATCH_MODE",
    "LOCATIONS",
    "EXPANSION_LOCATIONS",
    "EXCLUDE_DOMAINS",
)


def test_every_yaml_preset_has_a_one_word_category() -> None:
    missing = [
        preset_id
        for preset_id in discover_presets(use_cache=False)
        if preset_id not in PRESET_CATEGORY
    ]
    assert missing == []
    for preset_id in discover_presets(use_cache=True):
        assert category_for_preset(preset_id)


@pytest.mark.parametrize("preset_id", list(TRADE_PRESETS))
def test_trade_preset_is_a_france_only_paysagistes_clone(preset_id: str) -> None:
    expected = TRADE_PRESETS[preset_id]
    config = load_config(preset_id, require_keys=False)
    paysagistes = load_config("paysagistes", require_keys=False)

    assert config["LEAD_CATEGORY"] == expected["category"]
    assert config["TARGET_LEADS"] == 5000
    assert config["INSTANTLY_LIST_ID"] == ""
    assert config["INSTANTLY_DEDUP_LIST_IDS"] == []
    assert config["INSTANTLY_CAMPAIGN_ID"] == ""
    assert config["KEYWORDS"] == expected["keywords"]
    for keyword in expected["keywords"]:
        assert keyword in config["TAXONOMY_INCLUDED_KEYWORDS"]
    assert config["LOCATIONS"]
    assert config["EXPANSION_LOCATIONS"]
    for key in _SHARED_WITH_PAYSAGISTES:
        assert config[key] == paysagistes[key]
    assert format_query(config["KEYWORDS"][0], config["LOCATIONS"][0]).endswith(", France")

    included = list(config["TAXONOMY_INCLUDED_KEYWORDS"])
    excluded = taxonomy_excluded_keywords(config)
    accepted, _reason = matches_taxonomy(expected["accept"], included, excluded)
    rejected, reject_reason = matches_taxonomy(expected["reject"], included, excluded)
    assert accepted
    assert not rejected
    assert reject_reason.startswith("excluded:")

    result = validate_preset_runtime(preset_id)
    assert result.errors == []
