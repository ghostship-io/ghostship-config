"""The public model catalog: prices and the models that are free right now.

OpenCode keeps a copy of the public models.dev catalog in its cache. That
catalog carries the per-million-token rate of every model it can serve, so it
answers two questions the dashboard needs: what a model would cost, and which
models are currently free (a promotional free model such as
`minimax-m3.1-flash-free`, or a provider's permanent free tier).

Free is read from the catalog's own prices. A model is free when the catalog
prices input and output at zero; it is *promotional* when the model id or
name also says so, because those free models come and go.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Iterable

# Collector provider names mapped onto the catalog's provider keys. The first
# key is the provider's own catalog; the rest are fallbacks that carry the
# newest models (OpenCode publishes the current line of every provider).
PROVIDER_ALIASES = {
    "ollama": ("ollama-cloud", "ollama"),
    "opencode-go": ("opencode-go", "opencode"),
    "opencode": ("opencode",),
    "openrouter": ("openrouter",),
    "claude": ("anthropic", "opencode"),
    "codex": ("openai", "opencode"),
    "grok": ("xai", "opencode"),
    "antigravity": ("google", "opencode"),
    "google": ("google", "opencode"),
}

PRICE_KINDS = ("input", "output", "cache_read", "cache_write")

PROMO_MARKERS = ("-free", ":free", " free", "contributor", "free ")


def is_promo(model_id: str, name: str = "") -> bool:
    """True when the model id or name marks a promotional free model."""
    haystack = f"{model_id} {name}".lower()
    return any(marker in haystack for marker in PROMO_MARKERS)


def is_free_price(cost: Any) -> bool:
    """True when a catalog cost entry prices both input and output at zero."""
    if not isinstance(cost, dict):
        return False
    values = [cost.get("input"), cost.get("output")]
    if any(value is None for value in values):
        return False
    try:
        return all(float(value) == 0.0 for value in values)
    except (TypeError, ValueError):
        return False


def normalize_rates(cost: Any) -> dict[str, float]:
    """Return the per-million-token rates of one catalog cost entry."""
    if not isinstance(cost, dict):
        return {}
    rates: dict[str, float] = {}
    for kind in PRICE_KINDS:
        value = cost.get(kind)
        if value is None:
            continue
        try:
            rates[kind] = float(value)
        except (TypeError, ValueError):
            continue
    return rates


class Catalog:
    """A read-only view of the models.dev catalog."""

    def __init__(self, document: dict[str, Any] | None = None, *, updated_at: float | None = None) -> None:
        self.document = document or {}
        self.updated_at = updated_at

    @classmethod
    def load(cls, path: str | os.PathLike[str]) -> "Catalog":
        try:
            stat = os.stat(path)
            updated_at = stat.st_mtime
        except OSError:
            updated_at = None
        try:
            document = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            document = {}
        if not isinstance(document, dict):
            document = {}
        return cls(document, updated_at=updated_at)

    # -- lookups --------------------------------------------------------
    def _provider_models(self, provider: str) -> dict[str, Any]:
        """The models of a provider's own catalog."""
        for key in PROVIDER_ALIASES.get(provider, (provider,)):
            entry = self.document.get(key)
            if isinstance(entry, dict) and isinstance(entry.get("models"), dict):
                return entry["models"]
        return {}

    def _merged_models(self, provider: str) -> dict[str, Any]:
        """The models of a provider's own catalog plus the fallback catalogs."""
        merged: dict[str, Any] = {}
        for key in PROVIDER_ALIASES.get(provider, (provider,)):
            entry = self.document.get(key)
            if not isinstance(entry, dict) or not isinstance(entry.get("models"), dict):
                continue
            for model_id, model in entry["models"].items():
                merged.setdefault(model_id, model)
        return merged

    def price_for(self, provider: str, model: str) -> dict[str, float] | None:
        """Return the rates of one model, or None when the catalog is silent."""
        entry = self._merged_models(provider).get(model)
        if not isinstance(entry, dict):
            return None
        rates = normalize_rates(entry.get("cost"))
        return rates or None

    def model_entry(self, provider: str, model: str) -> dict[str, Any] | None:
        """Return the catalog entry of one model, or None."""
        entry = self._merged_models(provider).get(model)
        return entry if isinstance(entry, dict) else None

    def model_name(self, provider: str, model: str) -> str:
        entry = self.model_entry(provider, model)
        if isinstance(entry, dict):
            name = entry.get("name")
            if isinstance(name, str) and name:
                return name
        return model

    def free_models(self, provider: str) -> list[dict[str, Any]]:
        """Every catalog model of one provider that is currently free."""
        found: list[dict[str, Any]] = []
        for model_id, entry in self._provider_models(provider).items():
            if not isinstance(entry, dict):
                continue
            cost = entry.get("cost")
            if not is_free_price(cost):
                continue
            name = entry.get("name") if isinstance(entry.get("name"), str) else model_id
            found.append(
                {
                    "provider": provider,
                    "model": model_id,
                    "name": name,
                    "tier": "promo" if is_promo(model_id, name) else "free_tier",
                    "rates": normalize_rates(cost),
                }
            )
        return sorted(found, key=lambda row: (row["provider"], row["model"]))

    def all_free_models(self, providers: Iterable[str]) -> list[dict[str, Any]]:
        found: list[dict[str, Any]] = []
        for provider in providers:
            found.extend(self.free_models(provider))
        return found
