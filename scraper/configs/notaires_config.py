"""Notaires (France) — Outscraper taxonomy gate."""

from french_cities import FRENCH_EXPANSION_LOCATIONS, FRENCH_LOCATIONS

PRESET_ID = "notaires"
PRESET_LABEL = "Notaires (France)"

INSTANTLY_NAME = "Notaire"
SCRAPE_QUEUE_RANK = 9

_LIST_ID = "639a41b6-2493-4f19-878d-adf39ee6ce45"
_CAMPAIGN_ID = "56ae1754-8e75-4133-887f-2d1581ed2614"
_SUBSEQUENCE_ID = ""

NOTAIRES_CONFIG = {
    "OUTSCRAPER_API_KEY": "",
    "INSTANTLY_API_KEY": "",
    "INSTANTLY_NAME": INSTANTLY_NAME,
    "SCRAPE_QUEUE_RANK": SCRAPE_QUEUE_RANK,
    "INSTANTLY_LIST_ID": _LIST_ID,
    "INSTANTLY_CAMPAIGN_ID": _CAMPAIGN_ID,
    "INSTANTLY_SUBSEQUENCE_ID": _SUBSEQUENCE_ID,
    "INSTANTLY_DEDUP_LIST_IDS": [_LIST_ID] if _LIST_ID else [],
    "INSTANTLY_DEDUP_CAMPAIGN_IDS": [_CAMPAIGN_ID] if _CAMPAIGN_ID else [],
    "INSTANTLY_SKIP_IF_IN_CAMPAIGN": True,
    "INSTANTLY_SKIP_IF_IN_LIST": True,
    "INSTANTLY_PUSH_EVERY": 25,
    "INSTANTLY_BACKLOG_PUSH_MIN": 25,
    "INSTANTLY_PROVISION_LINKS": False,
    "ENRICH_ENABLED": False,
    "WEBSITE_REQUIRED": False,
    "OUTSCRAPER_FILTERS": ["operational_only"],
    "TAXONOMY_GATE_ENABLED": True,
    "TAXONOMY_MATCH_MODE": "taxonomy_only",
    "TAXONOMY_INCLUDED_KEYWORDS": [
        "notaire",
        "notaires",
        "office notarial",
        "étude notariale",
        "etude notariale",
        "notary public",
        "notary",
        "notaire associé",
        "notaire associe",
    ],
    "TAXONOMY_EXCLUDED_KEYWORDS": [
        "avocat",
        "huissier",
        "greffe",
        "tribunal",
        "recrutement",
        "assurance",
        "mutuelle",
        "logiciel juridique",
        "école",
        "ecole",
    ],
    "ENRICH_INCLUDED_KEYWORDS": [],
    "ENRICH_HARD_EXCLUDED_KEYWORDS": [],
    "ENRICH_SOFT_EXCLUDED_KEYWORDS": [],
    "OUTSCRAPER_BATCH_SIZE": 40,
    "OUTSCRAPER_CONCURRENCY": 16,
    "OUTSCRAPER_LIMIT_PER_QUERY": 200,
    "OUTSCRAPER_POLL_INITIAL_S": 10,
    "OUTSCRAPER_POLL_INTERVAL_S": 5,
    "OUTSCRAPER_POLL_SLOW_S": 10,
    "OUTSCRAPER_POLL_TIMEOUT_S": 600,
    "OUTSCRAPER_TOTAL_LIMIT_BUFFER": 12,
    "OUTSCRAPER_ENRICHMENT": ["leads_n_contacts"],
    "OUTSCRAPER_EMAIL_RECOVERY_ENABLED": True,
    "TARGET_LEADS": 3000,
    "TARGET_MODE": "instantly_pushed_run",
    "SCRAPE_START_QUERY_PASS": 0,
    "SCRAPE_SKIP_PHASE_ENABLED": False,
    "SCRAPE_SKIP_SATURATION_TO_DEPARTMENT": True,
    "DUPLICATE_GEO_ADVANCE_RATE": 0.50,
    "SCRAPE_RELOAD_ENABLED": True,
    "SCRAPE_RELOAD_MAX_ROUNDS": 8,
    "SCRAPE_RELOAD_START_GEO_PHASE": "pass",
    "SCRAPE_RELOAD_START_QUERY_PASS": 0,
    "SCRAPE_CONTINUOUS_MODE": True,
    "SCRAPE_CONTINUOUS_MAX_ZERO_CYCLES": 3,
    "CONTINUOUS_KEYWORD_ROTATIONS": [
        [
            "notaire",
            "office notarial",
            "étude notariale",
            "notaires",
        ],
        [
            "notary public",
            "notary",
            "notaire associé",
            "office notaires",
        ],
    ],
    "SERVICE_DEFAULT": "Notaire",
    "SERVICE_RULES": [],
    "KEYWORDS": [
        "notaire",
        "office notarial",
        "étude notariale",
        "notaires",
    ],
    "EXPANSION_KEYWORDS": [
        "notary public",
        "notary",
        "notaire associé",
    ],
    "LOCATIONS": FRENCH_LOCATIONS,
    "EXPANSION_LOCATIONS": FRENCH_EXPANSION_LOCATIONS,
    "EXCLUDE_DOMAINS": [
        "duckduckgo.com",
        "google.com",
        "google.fr",
        "facebook.com",
        "instagram.com",
        "linkedin.com",
        "youtube.com",
        "pinterest.com",
        "tiktok.com",
        "societe.com",
        "pagesjaunes.fr",
        "notaires.fr",
    ],
    "PAPPERS_ENABLED": False,
    "NICHE_METADATA": {
        "angle": "Institutionnels, faible appétit — signature la plus lente du portefeuille",
        "valeur_client": "Prospection études notariales",
        "effectif_cible": "études notariales",
        "priorite": 9,
    },
}

CONFIG = NOTAIRES_CONFIG
