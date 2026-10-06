"""Load repo .env and inject secrets into scraper config."""

from __future__ import annotations

import os
from collections.abc import Callable, Iterator, Mapping
from copy import deepcopy
from typing import Any

from dotenv import load_dotenv

from repo_paths import outreach_root

_LIB_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ENV = str(outreach_root() / ".env")
_LOCAL_ENV = os.path.join(_LIB_DIR, ".env")

# override=True: repo .env wins over stale VPS_* (etc.) exported in the shell/Streamlit parent.
if os.path.isfile(_REPO_ENV):
    load_dotenv(_REPO_ENV, override=True)
if os.path.isfile(_LOCAL_ENV):
    load_dotenv(_LOCAL_ENV, override=True)
load_dotenv()

DEFAULT_PRESET = "avocats"


class _PresetRegistry(Mapping[str, Callable[[], dict[str, Any]]]):
    def __getitem__(self, preset_id: str) -> Callable[[], dict[str, Any]]:
        registry = _get_registry()
        if preset_id not in registry:
            raise KeyError(preset_id)
        return registry[preset_id].loader

    def __iter__(self) -> Iterator[str]:
        return iter(_get_registry())

    def __len__(self) -> int:
        return len(_get_registry())

    def get(self, preset_id: str, default: Any = None) -> Any:
        registry = _get_registry()
        meta = registry.get(preset_id)
        if meta is None:
            return default
        return meta.loader


class _PresetLabels(Mapping[str, str]):
    def __getitem__(self, preset_id: str) -> str:
        return _get_registry()[preset_id].label

    def __iter__(self) -> Iterator[str]:
        return iter(_get_registry())

    def __len__(self) -> int:
        return len(_get_registry())

    def items(self) -> Any:
        return ((pid, meta.label) for pid, meta in _get_registry().items())

    def values(self) -> Any:
        return (meta.label for meta in _get_registry().values())


_registry_cache: dict[str, Any] | None = None


def _get_registry():
    global _registry_cache
    if _registry_cache is None:
        from bootstrap.discovery import discover_presets

        _registry_cache = discover_presets(use_cache=True)
    return _registry_cache


def invalidate_preset_registry() -> None:
    global _registry_cache
    _registry_cache = None
    from bootstrap.discovery import invalidate_preset_cache

    invalidate_preset_cache()


PRESETS: Mapping[str, Callable[[], dict[str, Any]]] = _PresetRegistry()
PRESET_LABELS: Mapping[str, str] = _PresetLabels()


def get_niche_groups() -> dict[str, list[tuple[str, str]]]:
    """Return {group_id: [(preset_id, label), ...]} for UI grouping."""
    from bootstrap.discovery import list_niche_groups

    return {
        group_id: [(m.preset_id, m.label) for m in metas]
        for group_id, metas in list_niche_groups().items()
    }


def _require_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise SystemExit(f"Missing required env var: {name} (set it in repo .env)")
    return value


def _env_int(name: str) -> int | None:
    raw = os.getenv(name, "").strip()
    if not raw:
        return None
    return int(raw)


def _inject_secrets(config: dict, *, require_keys: bool, preset: str) -> dict:
    config["OUTSCRAPER_API_KEY"] = os.getenv("OUTSCRAPER_API_KEY", "").strip()
    if require_keys:
        config["INSTANTLY_API_KEY"] = _require_env("INSTANTLY_API_KEY")
    else:
        config["INSTANTLY_API_KEY"] = os.getenv("INSTANTLY_API_KEY", "").strip()

    config["PAPPERS_API_KEY"] = os.getenv("PAPPERS_API_KEY", "").strip()

    preset_env_key = f"INSTANTLY_LIST_ID_{preset.upper()}"
    preset_list_id = os.getenv(preset_env_key, "").strip()
    global_list_id = os.getenv("INSTANTLY_LIST_ID", "").strip()

    if preset_list_id:
        config["INSTANTLY_LIST_ID"] = preset_list_id
    elif global_list_id and preset == DEFAULT_PRESET:
        config["INSTANTLY_LIST_ID"] = global_list_id

    from bootstrap.discovery import all_dedup_campaign_ids, all_dedup_list_ids, discover_presets

    presets = discover_presets(use_cache=True)
    meta = presets.get(preset)
    if meta is not None:
        config.setdefault("NICHE_GROUP", meta.niche_group)
        config.setdefault("NICHE_GROUP_LABEL", meta.niche_group_label)
        config.setdefault("SUBNICHE_LABEL", meta.subniche_label)

    group_lists = all_dedup_list_ids(preset)
    if group_lists:
        config["INSTANTLY_DEDUP_LIST_IDS"] = group_lists
    group_campaigns = all_dedup_campaign_ids(preset)
    if group_campaigns:
        config["INSTANTLY_DEDUP_CAMPAIGN_IDS"] = group_campaigns

    for env_key, cfg_key in (
        ("OUTSCRAPER_BATCH_SIZE", "OUTSCRAPER_BATCH_SIZE"),
        ("OUTSCRAPER_CONCURRENCY", "OUTSCRAPER_CONCURRENCY"),
        ("OUTSCRAPER_LIMIT_PER_QUERY", "OUTSCRAPER_LIMIT_PER_QUERY"),
        ("OUTSCRAPER_POLL_INITIAL_S", "OUTSCRAPER_POLL_INITIAL_S"),
        ("OUTSCRAPER_POLL_INTERVAL_S", "OUTSCRAPER_POLL_INTERVAL_S"),
        ("OUTSCRAPER_POLL_SLOW_S", "OUTSCRAPER_POLL_SLOW_S"),
        ("OUTSCRAPER_POLL_TIMEOUT_S", "OUTSCRAPER_POLL_TIMEOUT_S"),
        ("OUTSCRAPER_TOTAL_LIMIT_BUFFER", "OUTSCRAPER_TOTAL_LIMIT_BUFFER"),
        ("ENRICH_CONCURRENCY", "ENRICH_CONCURRENCY"),
        ("ENRICH_TIMEOUT_MS", "ENRICH_TIMEOUT_MS"),
        ("ENRICH_BATCH_SIZE", "ENRICH_BATCH_SIZE"),
    ):
        override = _env_int(env_key)
        if override is not None:
            config[cfg_key] = override

    return config


def load_config(preset: str = DEFAULT_PRESET, *, require_keys: bool = True) -> dict:
    loader = PRESETS.get(preset)
    if loader is None:
        known = ", ".join(sorted(PRESETS))
        raise SystemExit(f"Unknown preset {preset!r}. Available: {known}")

    config = deepcopy(loader())
    config["PRESET_ID"] = preset
    from shared.central_leads import category_for_preset

    try:
        config["LEAD_CATEGORY"] = category_for_preset(preset)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    for key, default in (
        ("OUTSCRAPER_BATCH_SIZE", 25),
        ("OUTSCRAPER_CONCURRENCY", 2),
        ("OUTSCRAPER_LIMIT_PER_QUERY", 50),
    ):
        config.setdefault(key, default)
    return _inject_secrets(config, require_keys=require_keys, preset=preset)


def load_biggy_config(*, require_keys: bool = True) -> dict:
    """Backward-compatible alias for the default preset."""
    return load_config(DEFAULT_PRESET, require_keys=require_keys)
