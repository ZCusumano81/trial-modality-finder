"""A tiny on-disk cache for web lookups (ChEMBL, Wikidata, Wikipedia).

Each answer is saved as a JSON file under cache/<source>/, so the same drug
is never looked up twice. Delete the cache/ folder to start fresh.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any, Callable

CACHE_DIR = Path(os.environ.get("TMF_CACHE_DIR", Path(__file__).resolve().parent.parent / "cache"))
MAX_AGE_DAYS = 90
_MISSING = object()


def _path(source: str, key: str) -> Path:
    digest = hashlib.sha1(key.lower().encode()).hexdigest()[:20]
    return CACHE_DIR / source / f"{digest}.json"


def get(source: str, key: str) -> Any:
    path = _path(source, key)
    try:
        if time.time() - path.stat().st_mtime > MAX_AGE_DAYS * 86400:
            return _MISSING
        return json.loads(path.read_text())["value"]
    except (OSError, ValueError, KeyError):
        return _MISSING


def put(source: str, key: str, value: Any) -> None:
    path = _path(source, key)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"key": key, "value": value}))
    except OSError:
        pass  # a read-only disk shouldn't break the app


def cached(source: str, key: str, fetch: Callable[[], Any]) -> Any:
    """Return the saved answer, or call fetch(), save and return it.

    If fetch() raises, nothing is saved, so a temporary outage is retried next time.
    """
    value = get(source, key)
    if value is not _MISSING:
        return value
    value = fetch()
    put(source, key, value)
    return value
