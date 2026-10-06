"""Re-export shared Instantly client for streamlit_clean."""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from shared.instantly_client import *  # noqa: F403
from shared import instantly_client as _shared  # noqa: E402

_get_client = _shared._get_client
get_api_key = _shared.get_api_key

__all__ = [name for name in dir(_shared) if not name.startswith("_")]
