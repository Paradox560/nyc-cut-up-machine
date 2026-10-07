"""Run `python3 -m cutup`, `python3 -m cutup check`, or `python3 -m cutup index`."""

import argparse
import json

from .config import load_config
from .providers import ElasticClient, MistralClient
from .server import serve
from .store import CorpusStore


def main():
    parser = argparse.ArgumentParser(description="StreetScript")
    parser.add_argument("command", nargs="?", choices=["serve", "check", "index"], default="serve")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--demo", action="store_true", help="Use clearly labeled synthetic fixtures without API calls")
    args = parser.parse_args()
    config = load_config()
    if args.command == "serve":
        if not 0 <= args.port <= 65535:
            parser.error("--port must be between 0 and 65535")
        serve(args.port, demo=args.demo)
    elif args.command == "check":
        for name, client in [("Mistral", MistralClient(config)), ("Elasticsearch", ElasticClient(config))]:
            print(name + ": " + json.dumps(client.check()))
    else:
        sources = [s for s in CorpusStore(config.data_dir).all() if not s.get("synthetic")]
        if not sources:
            parser.error("No archive sources to index. Run scripts/ingest.py first.")
        client = ElasticClient(config)
        for source in sources:
            client.index_source(source)
            print("Indexed " + source["id"] + (" (reviewed)" if source["reviewed"] else " (pending review)"))


if __name__ == "__main__":
    main()
