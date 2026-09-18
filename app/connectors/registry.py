"""Maps a source name to its connector instance.

Connector modules register themselves at import time (see
app/connectors/__init__.py once real connectors exist). Keeping this as a
plain dict, not a class, is deliberate — a broken connector module simply
fails to register rather than half-registering into shared mutable state.
"""

from __future__ import annotations

from app.connectors.base import SourceConnector

_REGISTRY: dict[str, SourceConnector] = {}


def register(connector: SourceConnector) -> SourceConnector:
    if connector.name in _REGISTRY:
        raise ValueError(f"connector '{connector.name}' is already registered")
    _REGISTRY[connector.name] = connector
    return connector


def get(name: str) -> SourceConnector:
    try:
        return _REGISTRY[name]
    except KeyError:
        raise KeyError(f"no connector registered for source '{name}'") from None


def all_connectors() -> dict[str, SourceConnector]:
    return dict(_REGISTRY)
