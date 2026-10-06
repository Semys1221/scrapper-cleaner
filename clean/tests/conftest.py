"""Put the cleaner package and the repo root on sys.path for this test process."""

from __future__ import annotations

import sys
from pathlib import Path

_CLEAN = Path(__file__).resolve().parents[1]
_ROOT = _CLEAN.parent
for _path in (str(_ROOT), str(_CLEAN)):
    if _path in sys.path:
        sys.path.remove(_path)
    sys.path.insert(0, _path)
