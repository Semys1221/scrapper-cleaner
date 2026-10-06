"""DAF à temps partagé (France) scraper preset — static rules; secrets come from config_loader."""

from french_cities import FRENCH_EXPANSION_LOCATIONS, FRENCH_LOCATIONS

PRESET_ID = "daf_partage"
PRESET_LABEL = "DAF à temps partagé (France)"

_LIST_ID = ""
_CAMPAIGN_ID = ""
_SUBSEQUENCE_ID = ""

DAF_PARTAGE_CONFIG = {
    "OUTSCRAPER_API_KEY": "",
    "INSTANTLY_API_KEY": "",
    "INSTANTLY_LIST_ID": _LIST_ID,
    "INSTANTLY_CAMPAIGN_ID": _CAMPAIGN_ID,
    "INSTANTLY_SUBSEQUENCE_ID": _SUBSEQUENCE_ID,
    "INSTANTLY_DEDUP_LIST_IDS": [_LIST_ID],
    "INSTANTLY_DEDUP_CAMPAIGN_IDS": [_CAMPAIGN_ID],
    "INSTANTLY_PUSH_EVERY": 100,
    "ENRICH_ENABLED": False,
    "ENRICH_BATCH_SIZE": 50,
    "ENRICH_CONCURRENCY": 20,
    "ENRICH_TIMEOUT_MS": 10000,
    "ENRICH_INCLUDED_KEYWORDS": [
        "temps partagé",
        "daf externalisé",
        "direction financière déléguée",
        "daf de transition",
    ],
    "ENRICH_HARD_EXCLUDED_KEYWORDS": [
        "expert-comptable",
        "expertise comptable",
        "recrutement",
        "cabinet de recrutement",
        "esn",
        "portage salarial",
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
    "SERVICE_DEFAULT": "DAF temps partagé",
    "SERVICE_RULES": [],
    "KEYWORDS": [
        "DAF temps partagé",
        "directeur financier partagé",
        "DAF externalisé",
        "DAF de transition",
    ],
    "EXPANSION_KEYWORDS": [
        "direction financière déléguée",
        "DAF externalisé",
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
        "angle": "Lead gen pour cabinets DAF temps partagé",
        "valeur_client": "Prise de RDV avec des cabinets DAF externalisé / transition",
        "effectif_cible": "3+ salariés",
    },
}

CONFIG = DAF_PARTAGE_CONFIG
