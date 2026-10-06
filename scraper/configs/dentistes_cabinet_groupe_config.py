"""Dentistes en cabinet de groupe (France) — structures multi-associés."""

from french_cities import FRENCH_EXPANSION_LOCATIONS, FRENCH_LOCATIONS

PRESET_ID = "dentistes_cabinet_groupe"
PRESET_LABEL = "Dentistes cabinet de groupe (France)"

_LIST_ID = "2d46a7b5-9c79-47fc-a250-7e8360bc50c5"
_CAMPAIGN_ID = "bba03f8f-7651-4f58-86b7-213c57890bbb"
_SUBSEQUENCE_ID = ""

INSTANTLY_NAME = "Dentiste cabinet de groupe"
SCRAPE_QUEUE_RANK = 7

DENTISTES_CABINET_GROUPE_CONFIG = {
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
    "INGESTER_MIN_SCORE": 0.50,
    "INGESTER_BORDERLINE_MIN": 0.30,
    "INGESTER_CONCURRENCY": 12,
    "INGESTER_FETCH_TIMEOUT": 8.0,
    "INGESTER_SIGNAL_WEIGHTS": {
        "taxonomy": 0.30,
        "website": 0.35,
        "review": 0.25,
        "registry": 0.10,
    },
    "INGESTER_REVIEW_ICP_KEYWORDS": [
        "cabinet",
        "associés",
        "associes",
        "équipe",
        "equipe",
        "clinique dentaire",
        "plusieurs",
    ],
    "INGESTER_REVIEW_ANTI_ICP_KEYWORDS": [
        "dentego",
        "réseau national",
        "franchise",
        "recrutement",
    ],
    "OUTSCRAPER_FILTERS": ["only_with_website", "operational_only"],
    "TAXONOMY_GATE_ENABLED": True,
    "TAXONOMY_INCLUDED_KEYWORDS": [
        "cabinet dentaire",
        "clinique dentaire",
        "centre dentaire",
        "chirurgien-dentiste",
        "chirurgien dentiste",
        "dentiste",
        "dental clinic",
    ],
    "TAXONOMY_EXCLUDED_KEYWORDS": [
        "dentego",
        "adental",
        "centre mutualiste",
        "laboratoire de prothèse",
        "prothésiste",
        "logiciel dentaire",
        "recrutement",
    ],
    "ENRICH_INCLUDED_KEYWORDS": [],
    "ENRICH_HARD_EXCLUDED_KEYWORDS": [],
    "ENRICH_SOFT_EXCLUDED_KEYWORDS": [],
    "OUTSCRAPER_BATCH_SIZE": 200,
    "OUTSCRAPER_CONCURRENCY": 16,
    "OUTSCRAPER_LIMIT_PER_QUERY": 50,
    "OUTSCRAPER_POLL_INITIAL_S": 10,
    "OUTSCRAPER_POLL_INTERVAL_S": 5,
    "OUTSCRAPER_POLL_SLOW_S": 10,
    "OUTSCRAPER_POLL_TIMEOUT_S": 300,
    "OUTSCRAPER_TOTAL_LIMIT_BUFFER": 8,
    "OUTSCRAPER_ENRICHMENT": ["leads_n_contacts"],
    "OUTSCRAPER_EMAIL_RECOVERY_ENABLED": True,
    "TARGET_LEADS": 3000,
    "TARGET_MODE": "instantly_pushed_run",
    "SERVICE_DEFAULT": "Cabinet dentaire",
    "SERVICE_RULES": [],
    "KEYWORDS": [
        "cabinet dentaire",
        "clinique dentaire",
        "chirurgiens-dentistes associés",
    ],
    "EXPANSION_KEYWORDS": [
        "cabinet pluridisciplinaire dentaire",
        "centre dentaire",
        "dentistes associés",
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
        "angle": "Cabinet structuré multi-associés (cycle plus long, souvent saturés)",
        "valeur_client": "Groupe de chirurgiens-dentistes / clinique dentaire",
        "effectif_cible": "plusieurs praticiens / associés",
        "priorite": 7,
    },
}

CONFIG = DENTISTES_CABINET_GROUPE_CONFIG
