"""Marchands e-commerce — boutiques en ligne, D2C, retail online (France)."""

from french_cities import FRENCH_EXPANSION_LOCATIONS, FRENCH_LOCATIONS

PRESET_ID = "boutiques_ecommerce"
PRESET_LABEL = "Marchands e-commerce (France)"

NICHE_GROUP = "ecommerce"
NICHE_GROUP_LABEL = "E-commerce"
SUBNICHE_LABEL = "Marchands / marques"

_RECEPTION_LIST_ID = "5fa7d7e3-07fc-4ba6-8ce6-0b4e55780884"
_MERCHANTS_LIST_ID = "1fdfa00a-680a-4a16-aa37-25a9f0e6e5aa"
_AGENCIES_LIST_ID = "f134a999-f8fe-4397-a5c9-39d432ddd2ef"
_CAMPAIGN_ID = ""
_SUBSEQUENCE_ID = ""

BOUTIQUES_ECOMMERCE_CONFIG = {
    "OUTSCRAPER_API_KEY": "",
    "INSTANTLY_API_KEY": "",
    "INSTANTLY_LIST_ID": _RECEPTION_LIST_ID,
    "INSTANTLY_CAMPAIGN_ID": _CAMPAIGN_ID,
    "INSTANTLY_SUBSEQUENCE_ID": _SUBSEQUENCE_ID,
    "INSTANTLY_DEDUP_LIST_IDS": [
        _RECEPTION_LIST_ID,
        _MERCHANTS_LIST_ID,
        _AGENCIES_LIST_ID,
    ],
    "INSTANTLY_DEDUP_CAMPAIGN_IDS": [],
    "INSTANTLY_SKIP_IF_IN_CAMPAIGN": False,
    "INSTANTLY_SKIP_IF_IN_LIST": True,
    "INSTANTLY_PUSH_EVERY": 50,
    "INSTANTLY_BACKLOG_PUSH_MIN": 50,
    "ENRICH_ENABLED": False,
    "WEBSITE_REQUIRED": True,
    "ENRICH_BATCH_SIZE": 50,
    "ENRICH_CONCURRENCY": 20,
    "ENRICH_TIMEOUT_MS": 10000,
    "ENRICH_INCLUDED_KEYWORDS": [
        "boutique en ligne",
        "e-commerce",
        "ecommerce",
        "shopify",
        "woocommerce",
        "prestashop",
        "ajouter au panier",
        "panier",
        "livraison",
        "paiement sécurisé",
        "vente en ligne",
        "e-shop",
    ],
    "ENRICH_HARD_EXCLUDED_KEYWORDS": [
        "agence web",
        "création de site",
        "développement web",
        "consultant",
        "amazon",
        "cdiscount",
        "etsy",
        "vinted",
        "leboncoin",
    ],
    "ENRICH_SOFT_EXCLUDED_KEYWORDS": [
        "agence digitale",
        "marketing digital",
    ],
    "OUTSCRAPER_BATCH_SIZE": 200,
    "OUTSCRAPER_CONCURRENCY": 10,
    "OUTSCRAPER_LIMIT_PER_QUERY": 50,
    "OUTSCRAPER_POLL_INITIAL_S": 20,
    "OUTSCRAPER_POLL_INTERVAL_S": 5,
    "OUTSCRAPER_POLL_SLOW_S": 10,
    "OUTSCRAPER_POLL_TIMEOUT_S": 600,
    "OUTSCRAPER_TOTAL_LIMIT_BUFFER": 8,
    "OUTSCRAPER_FILTERS": ["operational_only"],
    "TARGET_LEADS": 3000,
    "TARGET_MODE": "instantly_pushed",
    "SCRAPE_SKIP_PHASE_ENABLED": True,
    "SCRAPE_SKIP_SATURATION_TO_DEPARTMENT": True,
    "DUPLICATE_GEO_ADVANCE_RATE": 0.50,
    "SCRAPE_RELOAD_ENABLED": True,
    "SCRAPE_RELOAD_MAX_ROUNDS": 6,
    "SCRAPE_RELOAD_START_GEO_PHASE": "pass",
    "SCRAPE_RELOAD_START_QUERY_PASS": 0,
    "SCRAPE_CONTINUOUS_MODE": True,
    "SCRAPE_CONTINUOUS_MAX_ZERO_CYCLES": 5,
    "SERVICE_DEFAULT": "E-commerce",
    "SERVICE_RULES": [
        {
            "label": "Mode / D2C",
            "keywords": ["mode", "d2c", "marque", "concept store"],
        },
        {
            "label": "Retail online",
            "keywords": ["boutique en ligne", "e-shop", "vente en ligne"],
        },
    ],
    "KEYWORDS": [
        "boutique en ligne",
        "marque e-commerce",
        "e-shop",
        "vente en ligne",
        "boutique mode",
        "marque D2C",
        "concept store",
    ],
    "EXPANSION_KEYWORDS": [
        "boutique ecommerce",
        "marque en ligne",
        "showroom",
        "retail online",
        "direct to consumer",
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
    "PAPPERS_NAF_PREFIXES": ["47"],
    "SIRENE_INDEX_ENABLED": True,
    "SIRENE_INDEX_PATH": "data/sirene.db",
    "REGISTRY_DEEP_ENRICH": False,
    "REJECT_HOLDINGS": True,
    "NICHE_METADATA": {
        "angle": "Lead gen marchands e-commerce",
        "valeur_client": "Prise de RDV marques / boutiques online",
        "effectif_cible": "3+ salariés",
    },
}

CONFIG = BOUTIQUES_ECOMMERCE_CONFIG
