"""Chirurgiens plasticiens (France) — Outscraper taxonomy gate."""

from french_cities import FRENCH_EXPANSION_LOCATIONS, FRENCH_LOCATIONS

PRESET_ID = "chirurgiens_plasticiens"
PRESET_LABEL = "Chirurgiens plasticiens (France)"

_LIST_ID = "e36fdb0b-9ed4-4f2f-8f0e-e4d3472c1e64"
_CAMPAIGN_ID = "5bfbb212-6630-4319-846c-087f393f6464"
_SUBSEQUENCE_ID = ""

INSTANTLY_NAME = "Chirurgien plasticien"
SCRAPE_QUEUE_RANK = 1

CHIRURGIENS_PLASTICIENS_CONFIG = {
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
    "INSTANTLY_PROVISION_LINKS": False,
    "ENRICH_ENABLED": False,
    "INGESTER_ENABLED": True,
    "INGESTER_MIN_SCORE": 0.55,
    "INGESTER_BORDERLINE_MIN": 0.35,
    "INGESTER_CONCURRENCY": 12,
    "INGESTER_FETCH_TIMEOUT": 8.0,
    "INGESTER_SIGNAL_WEIGHTS": {
        "taxonomy": 0.35,
        "website": 0.35,
        "review": 0.20,
        "registry": 0.10,
    },
    "INGESTER_REVIEW_ICP_KEYWORDS": [
        "chirurgie esthétique",
        "plasticien",
        "lifting",
        "liposuccion",
        "augmentation",
        "rhinoplastie",
        "consultation",
    ],
    "INGESTER_REVIEW_ANTI_ICP_KEYWORDS": [
        "logiciel",
        "recrutement",
        "formation",
        "école",
        "mutuelle",
    ],
    "OUTSCRAPER_FILTERS": ["only_with_website", "operational_only"],
    "TAXONOMY_GATE_ENABLED": True,
    "TAXONOMY_INCLUDED_KEYWORDS": [
        "chirurgien plasticien",
        "chirurgie plastique",
        "chirurgie esthétique",
        "plastic surgeon",
        "plastic surgery clinic",
        "cosmetic surgeon",
        "clinique esthétique",
    ],
    "TAXONOMY_EXCLUDED_KEYWORDS": [
        "dentiste",
        "dentaire",
        "kinésithérapeute",
        "recrutement",
        "logiciel",
        "école",
        "université",
    ],
    "ENRICH_INCLUDED_KEYWORDS": [],
    "ENRICH_HARD_EXCLUDED_KEYWORDS": [],
    "ENRICH_SOFT_EXCLUDED_KEYWORDS": [],
    "OUTSCRAPER_BATCH_SIZE": 200,
    "OUTSCRAPER_CONCURRENCY": 2,
    "OUTSCRAPER_LIMIT_PER_QUERY": 400,
    "OUTSCRAPER_POLL_INITIAL_S": 45,
    "OUTSCRAPER_POLL_INTERVAL_S": 5,
    "OUTSCRAPER_POLL_SLOW_S": 10,
    "OUTSCRAPER_POLL_TIMEOUT_S": 600,
    "OUTSCRAPER_TOTAL_LIMIT_BUFFER": 8,
    "OUTSCRAPER_ENRICHMENT": ["leads_n_contacts"],
    "OUTSCRAPER_EMAIL_RECOVERY_ENABLED": True,
    "TARGET_LEADS": 3000,
    "TARGET_MODE": "instantly_pushed_run",
    "SERVICE_DEFAULT": "Chirurgie plastique",
    "SERVICE_RULES": [],
    "KEYWORDS": [
        "chirurgien plasticien",
        "chirurgie esthétique",
        "clinique chirurgie plastique",
    ],
    "EXPANSION_KEYWORDS": [
        "plastic surgeon",
        "cosmetic surgery",
        "chirurgie plastique",
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
    "NICHE_METADATA": {
        "angle": "Décret communication 23 sept. 2026 + ticket 3–10 k€ par acte",
        "valeur_client": "Chirurgien plasticien indépendant, décideur solo, concurrence online forte",
        "effectif_cible": "cabinets / cliniques indépendants",
        "priorite": 1,
    },
}

CONFIG = CHIRURGIENS_PLASTICIENS_CONFIG
