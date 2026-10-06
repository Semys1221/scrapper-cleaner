"""The cleaner suite must not call Supabase."""

from __future__ import annotations

import os


def test_supabase_url_is_unset() -> None:
    for key in ("SUPABASE_URL", "NEXT_PUBLIC_SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY"):
        assert os.environ.get(key, "").strip() == ""
