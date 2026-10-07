"""Readonly packaged sources and durable Elasticsearch composition snapshots."""

import re

from .elastic import ElasticClient
from .http_client import ProviderError
from .store import CorpusStore


class HostedStore(CorpusStore):
    def __init__(self, config):
        super().__init__(config.data_dir)
        self.client = ElasticClient(config)
        self.index = config.index + "-compositions"

    def upsert(self, source):
        raise ProviderError("Source review is available in the local workshop only.",
                            status=403, code="source_review_disabled")

    def save_composition(self, composition):
        identifier = composition.get("id")
        if not isinstance(identifier, str) or not re.fullmatch(r"[a-f0-9]{32}", identifier):
            raise ValueError("Invalid composition identifier.")
        path = "/" + self.index
        try:
            self.client.request(path, method="HEAD")
        except ProviderError as error:
            if error.code != "elasticsearch_404":
                raise
            try:
                self.client.request(path, method="PUT", payload={"mappings": {
                    "dynamic": "strict", "properties": {
                        "composition": {"type": "object", "enabled": False}
                    }}})
            except ProviderError as creation_error:
                if creation_error.code != "elasticsearch_400":
                    raise
                # Another cold instance may have created the same index.
                self.client.request(path, method="HEAD")
        self.client.request(f"{path}/_doc/{identifier}", method="PUT",
                            payload={"composition": composition})

    def get_composition(self, identifier):
        if not isinstance(identifier, str) or not re.fullmatch(r"[a-f0-9]{32}", identifier):
            return None
        try:
            result = self.client.request(f"/{self.index}/_doc/{identifier}")
        except ProviderError as error:
            if error.code == "elasticsearch_404":
                return None
            raise
        composition = result.get("_source", {}).get("composition")
        if not isinstance(composition, dict) or composition.get("id") != identifier:
            raise ProviderError("The saved composition could not be read.", code="invalid_composition")
        return composition
