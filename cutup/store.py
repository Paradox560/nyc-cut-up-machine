"""Atomic local persistence; archive assets and generated work stay out of Git."""

import json
from pathlib import Path
import re
from threading import RLock
import tempfile

from .provenance import validate_source

LOCK = RLock()


def atomic_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    name = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
            name = handle.name
            json.dump(value, handle, ensure_ascii=False, indent=2)
        Path(name).replace(path)
    finally:
        if name:
            Path(name).unlink(missing_ok=True)


class CorpusStore:
    def __init__(self, data_dir: Path):
        self.data_dir = Path(data_dir)
        self.path = self.data_dir / "corpus.json"

    def all(self) -> list[dict]:
        with LOCK:
            if not self.path.exists():
                return []
            return [validate_source(s) for s in json.loads(self.path.read_text(encoding="utf-8"))]

    def get(self, source_id: str) -> dict | None:
        return next((s for s in self.all() if s["id"] == source_id), None)

    def upsert(self, source: dict) -> dict:
        source = validate_source(source)
        with LOCK:
            sources = {s["id"]: s for s in self.all()}
            sources[source["id"]] = source
            atomic_json(self.path, list(sources.values()))
        return source

    def save_composition(self, composition: dict) -> None:
        identifier = composition["id"]
        if not re.fullmatch(r"[a-f0-9]{32}", identifier):
            raise ValueError("Invalid composition identifier.")
        with LOCK:
            atomic_json(self.data_dir / "compositions" / f"{identifier}.json", composition)

    def get_composition(self, identifier: str) -> dict | None:
        if not re.fullmatch(r"[a-f0-9]{32}", identifier):
            return None
        path = self.data_dir / "compositions" / f"{identifier}.json"
        with LOCK:
            return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def application_store(config):
    """Use durable remote composition storage only in the hosted deployment."""
    if config.hosted:
        from .hosted_store import HostedStore
        return HostedStore(config)
    return CorpusStore(config.data_dir)
