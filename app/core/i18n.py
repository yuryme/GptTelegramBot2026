from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=1)
def _load_ru() -> dict[str, str]:
    base_dir = Path(__file__).resolve().parents[2]
    path = base_dir / "locales" / "ru.json"
    return json.loads(path.read_text(encoding="utf-8"))


def t(key: str) -> str:
    data = _load_ru()
    return data.get(key, key)
