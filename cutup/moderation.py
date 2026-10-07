"""Mistral moderation for the brief and for the finished composition.

The call goes through the same MistralClient the composer already uses, so it needs no extra
configuration. Set CUTUP_MODERATION=off to switch it off (for example if the moderation
endpoint is rate limited right before a demo). Off is announced in the trace, never silent.
"""

import os

MODEL = "mistral-moderation-latest"


def enabled() -> bool:
    return os.environ.get("CUTUP_MODERATION", "on").strip().lower() != "off"


def interpret(result) -> dict:
    """Turn a /v1/moderations response into {flagged, categories, top}."""
    try:
        entry = result["results"][0]
        categories = entry.get("categories") or {}
        scores = entry.get("category_scores") or {}
    except (TypeError, KeyError, IndexError, AttributeError):
        raise ValueError("Unexpected moderation response.") from None
    flagged = sorted(name for name, value in categories.items() if value is True)
    top = max(scores.items(), key=lambda item: item[1]) if scores else (None, 0.0)
    return {"flagged": bool(flagged), "categories": flagged, "top": {"category": top[0], "score": round(float(top[1]), 4)}}


def check_text(client, text: str) -> dict:
    """Moderate text with an existing MistralClient. Long text is truncated to a safe size."""
    return interpret(client.request("/moderations", {"model": MODEL, "input": [text[:8000]]}))
