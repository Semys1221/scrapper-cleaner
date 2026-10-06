"""The cleaner suite must not call a non-local Supabase."""

from __future__ import annotations

import os

from test_hermetic import host_is_local


def test_supabase_url_is_local_or_unset() -> None:
    for key in ("SUPABASE_URL", "NEXT_PUBLIC_SUPABASE_URL"):
        value = os.environ.get(key, "").strip()
        assert value == "" or host_is_local(value)
