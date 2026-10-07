"""Read local settings without interpolating or printing credentials."""

from dataclasses import dataclass, field
import os
from pathlib import Path
import re
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent


def read_env(path: Path) -> dict[str, str]:
    values = {}
    if path.exists():
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.removeprefix("export ").split("=", 1)
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            values[key.strip()] = value
    return values


@dataclass(frozen=True)
class Config:
    project_root: Path = ROOT
    data_dir: Path = ROOT / "data"
    mistral_api_key: str = field(default="", repr=False)
    elasticsearch_url: str = ""
    elasticsearch_api_key: str = field(default="", repr=False)
    index: str = "nyc-cut-up-machine"
    chat_model: str = "mistral-large-4"
    ocr_model: str = "mistral-ocr-latest"
    embed_model: str = "mistral-embed"
    voice_id: str = ""
    tts_model: str = "voxtral-mini-tts-latest"

    @property
    def configured(self) -> bool:
        return bool(self.mistral_api_key and self.elasticsearch_url and self.elasticsearch_api_key)


def load_config(project_root: Path = ROOT) -> Config:
    values = {**read_env(project_root / ".env.local"), **os.environ}
    endpoint = values.get("ELASTICSEARCH_URL", "").strip().rstrip("/")
    if endpoint:
        parsed = urlparse(endpoint)
        try:
            parsed.port
        except ValueError:
            raise ValueError("ELASTICSEARCH_URL has an invalid port.") from None
        local_http = parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1"}
        if not (parsed.scheme == "https" or local_http) or not parsed.hostname:
            raise ValueError("ELASTICSEARCH_URL must use HTTPS (HTTP is allowed for localhost).")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("Use a plain Elasticsearch endpoint URL and a separate API key.")
    index = values.get("ELASTICSEARCH_INDEX", "nyc-cut-up-machine")
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,99}", index):
        raise ValueError("ELASTICSEARCH_INDEX must be a simple lowercase index name.")
    return Config(
        project_root=project_root,
        data_dir=project_root / "data",
        mistral_api_key=values.get("MISTRAL_API_KEY", "").strip(),
        elasticsearch_url=endpoint,
        elasticsearch_api_key=values.get("ELASTICSEARCH_API_KEY", "").strip(),
        index=index,
        chat_model=values.get("MISTRAL_CHAT_MODEL", "mistral-large-4"),
        ocr_model=values.get("MISTRAL_OCR_MODEL", "mistral-ocr-latest"),
        embed_model=values.get("MISTRAL_EMBED_MODEL", "mistral-embed"),
        voice_id=values.get("MISTRAL_VOICE_ID", "").strip(),
        tts_model=values.get("MISTRAL_TTS_MODEL", "voxtral-mini-tts-latest"),
    )
