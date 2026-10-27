"""Model prices. The agent never quotes a price from memory: it asks this catalog."""

from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass(frozen=True)
class CatalogEntry:
    provider: str
    model_id: str
    capability: str
    prices: dict
    synced_at: str


class ModelCatalog:
    def __init__(self, entries: list[CatalogEntry]):
        self._entries = entries

    @classmethod
    def load(cls, path: Path) -> "ModelCatalog":
        if not Path(path).exists():
            return cls([])
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        return cls(
            [
                CatalogEntry(
                    provider=item["provider"],
                    model_id=item["model_id"],
                    capability=item["capability"],
                    prices=item.get("prices", {}),
                    synced_at=str(item["synced_at"]),
                )
                for item in data.get("models", [])
            ]
        )

    def lookup(self, query: str) -> list[CatalogEntry]:
        """Exact model id first; otherwise every model with that capability (text, image, video)."""
        needle = query.strip().casefold()
        exact = [e for e in self._entries if e.model_id.casefold() == needle]
        return exact or [e for e in self._entries if e.capability.casefold() == needle]
