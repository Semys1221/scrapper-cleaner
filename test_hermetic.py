"""Keep pytest off live Supabase, Outscraper, Instantly, and Pappers."""

from __future__ import annotations

import os
from urllib.parse import urlparse

_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}
_URL_KEYS = ("SUPABASE_URL", "NEXT_PUBLIC_SUPABASE_URL")
_SECRET_KEYS = ("OUTSCRAPER_API_KEY", "INSTANTLY_API_KEY", "PAPPERS_API_KEY")


def host_is_local(url: str) -> bool:
    host = (urlparse(url).hostname or "").strip().lower()
    return host in _LOCAL_HOSTS


def strip_nonlocal_credentials(monkeypatch) -> None:
    """Drop live credentials. A localhost URL is left in place."""
    remote = False
    for key in _URL_KEYS:
        value = os.environ.get(key, "").strip()
        if value and not host_is_local(value):
            remote = True
            monkeypatch.delenv(key, raising=False)
    if remote:
        monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)
    for key in _SECRET_KEYS:
        monkeypatch.delenv(key, raising=False)
    try:
        from shared.central_leads import reset_supabase_store_cache

        reset_supabase_store_cache()
    except Exception:
        return
