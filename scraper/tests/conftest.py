"""Put the scraper package and the repo root on sys.path for this test process."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_SCRAPER = Path(__file__).resolve().parents[1]
_ROOT = _SCRAPER.parent
for _path in (str(_ROOT), str(_SCRAPER)):
    if _path in sys.path:
        sys.path.remove(_path)
    sys.path.insert(0, _path)

from test_hermetic import strip_nonlocal_credentials  # noqa: E402


@pytest.fixture(autouse=True)
def _hermetic_external_services(monkeypatch: pytest.MonkeyPatch) -> None:
    strip_nonlocal_credentials(monkeypatch)
