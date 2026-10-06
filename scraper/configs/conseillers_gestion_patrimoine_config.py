"""CGP et courtiers (France) scraper preset — static rules; secrets come from config_loader."""

from french_cities import FRENCH_EXPANSION_LOCATIONS, FRENCH_LOCATIONS

PRESET_ID = "conseillers_gestion_patrimoine"
PRESET_LABEL = "CGP et courtiers (France)"

_LIST_ID = "4a616678-06a0-44d2-a27c-f9248a4c34bf"
_CAMPAIGN_ID = "e3bdb573-fe9f-437d-bd96-4ceb52869dd4"
_SUBSEQUENCE_ID = "d656122e-fb42-42ac-a8c9-324eb9a13b86"

CONSEILLERS_GESTION_PATRIMOINE_CONFIG = {
    "OUTSCRAPER_API_KEY": "",
    "INSTANTLY_API_KEY": "",
    "INSTANTLY_LIST_ID": _LIST_ID,
    "INSTANTLY_CAMPAIGN_ID": _CAMPAIGN_ID,
    "INSTANTLY_SUBSEQUENCE_ID": _SUBSEQUENCE_ID,
    "INSTANTLY_DEDUP_LIST_IDS": [_LIST_ID, "edfd3090-6306-4f71-bd83-01192b06666c"],
    "INSTANTLY_DEDUP_CAMPAIGN_IDS": [_CAMPAIGN_ID],
    "INSTANTLY_PUSH_EVERY": 100,
    "INSTANTLY_PROVISION_LINKS": True,
    "LINK_PROVISION_CATEGORY": "cif",
    "ENRICH_ENABLED": False,
    "ENRICH_BATCH_SIZE": 50,
    "ENRICH_CONCURRENCY": 20,
    "ENRICH_TIMEOUT_MS": 10000,
    "ENRICH_INCLUDED_KEYWORDS": [
        "gestion de patrimoine",
        "conseiller en investissements financiers",
        "courtier",
        "cgp",
        "cif",
    ],
    "ENRICH_HARD_EXCLUDED_KEYWORDS": [
        "crédit agricole",
        "bnp paribas",
        "société générale",
        "banque populaire",
        "caisse d'épargne",
        "axa",
        "fortuneo",
        "linxea",
        "mutuelle",
    ],
    "ENRICH_SOFT_EXCLUDED_KEYWORDS": [],
    "OUTSCRAPER_BATCH_SIZE": 200,
    "OUTSCRAPER_CONCURRENCY": 6,
    "OUTSCRAPER_LIMIT_PER_QUERY": 30,
    "OUTSCRAPER_POLL_INITIAL_S": 45,
    "OUTSCRAPER_POLL_INTERVAL_S": 5,
    "OUTSCRAPER_POLL_SLOW_S": 10,
    "OUTSCRAPER_POLL_TIMEOUT_S": 600,
    "OUTSCRAPER_TOTAL_LIMIT_BUFFER": 8,
    "TARGET_LEADS": 3000,
    "TARGET_MODE": "instantly_pushed",
    "SERVICE_DEFAULT": "Gestion de patrimoine",
    "SERVICE_RULES": [],
    "KEYWORDS": [
        "conseiller gestion patrimoine",
        "CGP",
        "CGPI",
        "CIF",
        "courtier assurance",
    ],
    "EXPANSION_KEYWORDS": [
        "gestion de patrimoine",
        "courtier en assurance",
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
    ],
    "PAPPERS_ENABLED": False,
    "PAPPERS_MIN_EMPLOYEES": 3,
    "PAPPERS_MIN_SCORE": 55,
    "PAPPERS_SCORING_ENABLED": True,
    "PAPPERS_ON_UNKNOWN": "reject",
    "PAPPERS_CONCURRENCY": 50,
    "PAPPERS_NAF_PREFIXES": [],
    "SIRENE_INDEX_ENABLED": True,
    "SIRENE_INDEX_PATH": "data/sirene.db",
    "REGISTRY_DEEP_ENRICH": False,
    "REJECT_HOLDINGS": True,
    "NICHE_METADATA": {
        "angle": "Lead gen pour cabinets CGP et courtiers",
        "valeur_client": "Prise de RDV avec des cabinets patrimoine / assurance",
        "effectif_cible": "3+ salariés",
    },
}

CONFIG = CONSEILLERS_GESTION_PATRIMOINE_CONFIG
