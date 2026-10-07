"""Elasticsearch is the live vocabulary retrieval layer, including Mistral vectors."""

from urllib.parse import quote

from .config import Config
from .http_client import ProviderError, request_json
from .mistral import MistralClient
from .provenance import validate_source

MAPPING = {"mappings": {"properties": {
    "id": {"type": "keyword"}, "title": {"type": "text"},
    "borough": {"type": "keyword"}, "block": {"type": "keyword"}, "lot": {"type": "keyword"},
    "ocr_text": {"type": "text"}, "reviewed": {"type": "boolean"}, "synthetic": {"type": "boolean"},
    "words": {"type": "object", "enabled": False},
    "word_crops": {"type": "object", "enabled": False},
    "letter_crops": {"type": "object", "enabled": False},
    "letters": {"type": "object", "enabled": False},
    "letter_chars": {"type": "keyword"}, "has_letters": {"type": "boolean"},
    "image_sha256": {"type": "keyword", "index": False},
    "image_width": {"type": "integer"}, "image_height": {"type": "integer"},
    "embedding": {"type": "dense_vector", "dims": 1024, "index": True, "similarity": "cosine"},
    "image_url": {"type": "keyword", "index": False},
    "source_url": {"type": "keyword", "index": False}, "attribution": {"type": "text", "index": False},
}}}


class ElasticClient:
    def __init__(self, config: Config):
        self.config = config

    def request(self, path: str, payload=None, method: str = "GET"):
        if not self.config.elasticsearch_url or not self.config.elasticsearch_api_key:
            raise ProviderError("Add the Elasticsearch endpoint and API key to .env.local.", code="missing_elastic_key")
        return request_json(self.config.elasticsearch_url + path,
                            headers={"Authorization": "ApiKey " + self.config.elasticsearch_api_key},
                            payload=payload, method=method, service="Elasticsearch")

    def check(self) -> dict:
        result = self.request("/")
        return {"ok": True, "version": result.get("version", {}).get("number", "unknown")}

    def ensure_index(self) -> None:
        try:
            self.request("/" + self.config.index, method="HEAD")
        except ProviderError as exc:
            if exc.code != "elasticsearch_404":
                raise
            self.request("/" + self.config.index, payload=MAPPING, method="PUT")
        else:
            # Existing installations need the crop field disabled before indexing
            # token-specific metadata, just like the derived words array.
            self.request("/" + self.config.index + "/_mapping", method="PUT",
                         payload={"properties": {key: MAPPING["mappings"]["properties"][key]
                             for key in ("word_crops", "letter_crops", "letters", "letter_chars", "has_letters",
                                         "image_sha256", "image_width", "image_height")}})

    def index_source(self, source: dict) -> None:
        document = validate_source(source)
        if document.get("synthetic"):
            raise ValueError("Synthetic fixtures must not enter the archival index.")
        self.ensure_index()
        document["letter_chars"] = sorted({glyph["text"].casefold() for glyph in document["letters"]})
        document["has_letters"] = bool(document["letters"])
        document["embedding"] = MistralClient(self.config).embed([document["ocr_text"]])[0]
        self.request(f"/{self.config.index}/_doc/{quote(document['id'], safe='')}?refresh=wait_for",
                     payload=document, method="PUT")

    def search(self, query: str, *, include_unreviewed: bool = False, limit: int = 12) -> list[dict]:
        vector = MistralClient(self.config).embed([query])[0]
        filters = [{"term": {"reviewed": True}}] if not include_unreviewed else []
        filters.append({"bool": {"must_not": [{"term": {"synthetic": True}}]}})
        result = self.request(f"/{self.config.index}/_search", method="POST", payload={
            "size": limit, "_source": {"excludes": ["embedding"]},
            "retriever": {"rrf": {"retrievers": [
                {"standard": {"query": {"bool": {"must": [{"multi_match": {
                    "query": query, "fields": ["ocr_text^3", "title"]}}], "filter": filters}}}},
                {"knn": {"field": "embedding", "query_vector": vector, "k": 30,
                         "num_candidates": 100, "filter": {"bool": {"filter": filters}}}},
            ], "rank_window_size": 50, "rank_constant": 60}},
        })
        return [validate_source(hit["_source"]) for hit in result.get("hits", {}).get("hits", [])]

    def find_words(self, query: str, *, limit: int = 8) -> list[dict]:
        """Rank reviewed photographs for a query (BM25 + Mistral vectors, RRF) and show their words."""
        results = []
        for rank, source in enumerate(self.search(query, include_unreviewed=False, limit=limit), start=1):
            words = [w["text"] for w in source["words"] if not w["text"].isdigit()]
            results.append({"rank": rank, "source_id": source["id"], "title": source.get("title", ""),
                            "words": words[:12]})
        return results

    def glyph_sources(self, *, include_unreviewed: bool = False) -> list[dict]:
        """Supplement semantic retrieval with a reusable photographed alphabet."""
        filters = [{"term": {"has_letters": True}}]
        if not include_unreviewed:
            filters.append({"term": {"reviewed": True}})
        result = self.request(f"/{self.config.index}/_search", method="POST", payload={
            "size": 64, "_source": {"excludes": ["embedding"]}, "sort": [{"id": "asc"}],
            "query": {"bool": {"filter": filters, "must_not": [{"term": {"synthetic": True}}]}},
        })
        return [validate_source(hit["_source"]) for hit in result.get("hits", {}).get("hits", [])]
