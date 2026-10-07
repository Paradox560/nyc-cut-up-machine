"""Mistral OCR, embeddings, constrained composition, and optional speech."""

import base64
import json
from pathlib import Path

from .config import Config
from .http_client import ProviderError, request_json


class MistralClient:
    def __init__(self, config: Config):
        self.config = config

    def request(self, path: str, payload=None, method: str = "POST"):
        if not self.config.mistral_api_key:
            raise ProviderError("Add MISTRAL_API_KEY to .env.local.", code="missing_mistral_key")
        return request_json("https://api.mistral.ai/v1" + path,
                            headers={"Authorization": "Bearer " + self.config.mistral_api_key},
                            payload=payload, method=method, service="Mistral")

    def check(self) -> dict:
        result = self.request("/models", method="GET")
        ids = [m.get("id") for m in result.get("data", [])]
        return {"ok": True, "chat_model_available": self.config.chat_model in ids,
                "configured_chat_model": self.config.chat_model}

    def ocr(self, image_path: Path) -> str:
        data = Path(image_path).read_bytes()
        if len(data) > 15_000_000:
            raise ProviderError("The archive image exceeds the 15 MB ingestion limit.")
        if data.startswith(b"\x89PNG\r\n\x1a\n"):
            mime = "image/png"
        elif data.startswith(b"\xff\xd8\xff"):
            mime = "image/jpeg"
        else:
            raise ProviderError("OCR accepts only downloaded JPEG or PNG archive images.")
        result = self.request("/ocr", {
            "model": self.config.ocr_model,
            "document": {"type": "image_url", "image_url": "data:" + mime + ";base64," + base64.b64encode(data).decode()},
            "include_image_base64": False,
        })
        text = "\n".join(page.get("markdown", "") for page in result.get("pages", []))
        if not text.strip():
            raise ProviderError("Mistral found no readable text in this image.", code="empty_ocr")
        return text

    def embed(self, texts: list[str]) -> list[list[float]]:
        result = self.request("/embeddings", {"model": self.config.embed_model, "input": texts})
        data = sorted(result.get("data", []), key=lambda d: d["index"])
        if len(data) != len(texts) or any(len(d.get("embedding", [])) != 1024 for d in data):
            raise ProviderError("Expected one 1024-dimensional Mistral embedding per input.")
        return [d["embedding"] for d in data]

    def compose(self, messages: list[dict]) -> dict:
        schema = {"type": "object", "properties": {"lines": {"type": "array", "items": {
            "type": "array", "items": {"type": "string"}}}}, "required": ["lines"], "additionalProperties": False}
        result = self.request("/chat/completions", {
            "model": self.config.chat_model, "messages": messages, "temperature": 0.8,
            "max_tokens": 3000,
            "response_format": {"type": "json_schema", "json_schema": {
                "name": "cut_up_composition", "schema": schema, "strict": True}},
        })
        try:
            return json.loads(result["choices"][0]["message"]["content"])
        except (KeyError, IndexError, TypeError, ValueError):
            raise ProviderError("Mistral did not return a usable structured composition.", code="invalid_composition") from None

    def speech(self, text: str) -> bytes:
        if not self.config.voice_id:
            raise ProviderError("Set MISTRAL_VOICE_ID to enable Voxtral speech.", status=409, code="voice_not_configured")
        result = self.request("/audio/speech", {
            "model": self.config.tts_model, "input": text, "voice_id": self.config.voice_id,
            "response_format": "mp3",
        })
        try:
            return base64.b64decode(result["audio_data"], validate=True)
        except (KeyError, ValueError, TypeError):
            raise ProviderError("Mistral returned an invalid audio response.") from None
