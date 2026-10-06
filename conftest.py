"""Hermetic defaults for pytest processes started at the repo root."""

from __future__ import annotations

import pytest

from test_hermetic import strip_nonlocal_credentials


@pytest.fixture(autouse=True)
def _hermetic_external_services(monkeypatch: pytest.MonkeyPatch) -> None:
    strip_nonlocal_credentials(monkeypatch)
