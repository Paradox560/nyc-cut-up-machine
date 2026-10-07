"""Explicitly synthetic vocabulary for trying the UI without API credentials."""

from .provenance import build_words

SAMPLES = [
    ("sample-01", "THE CITY IS OPEN ALL NIGHT LOVE LETTERS LOST AND FOUND HERE"),
    ("sample-02", "WE REPAIR BROKEN HEARTS WHILE YOU WAIT GOOD THINGS TAKE TIME"),
    ("sample-03", "NO MORE CREDIT EVERYTHING MUST GO THANK YOU FOR YOUR BUSINESS"),
    ("sample-04", "NEW YORK FINE WORDS OLD SOULS COME HOME SOON ALWAYS YOURS"),
]


def demo_sources() -> list[dict]:
    return [
        {"id": identifier, "title": f"Sample vocabulary {i + 1}", "borough": "Synthetic sample",
         "block": "", "lot": "", "image_url": "", "source_url": "",
         "attribution": "Synthetic fixture for interface testing. Not archival evidence.",
         "ocr_text": text, "reviewed": False, "synthetic": True,
         "words": build_words(identifier, text)}
        for i, (identifier, text) in enumerate(SAMPLES)
    ]


def demo_selection(form: str, sources: list[dict]) -> dict:
    templates = {
        "poem": ["THE CITY IS OPEN", "ALL NIGHT", "LOST SOULS COME HOME"],
        "love-letter": ["DEAR" , "GOOD THINGS TAKE TIME", "COME HOME SOON", "ALWAYS YOURS"],
        "breakup-letter": ["NO MORE CREDIT", "EVERYTHING MUST GO", "THANK YOU FOR YOUR BUSINESS"],
        "manifesto": ["WE REPAIR THE CITY", "WE REPAIR BROKEN HEARTS", "GOOD WORDS FOR ALL"],
    }
    vocabulary = {w["text"]: w["id"] for s in sources for w in s["words"]}
    # A fixture deliberately has no general language generation or service calls.
    lines = [[vocabulary[w] for w in line.split() if w in vocabulary]
             for line in templates.get(form, templates["poem"])]
    return {"lines": [line for line in lines if line]}
