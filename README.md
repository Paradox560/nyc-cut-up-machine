# NYC Cut-Up Machine

**Write something new using only words New York put on its buildings.**

A found-poetry print shop built for the [Elastic × Mistral NYC Hack Night](https://github.com/AvenueJ/elastic-mistral-hacknight). It retrieves words from historical NYC storefront photographs, composes a poem or letter, and gives every printed word a clickable source. Export a standalone SVG poster with archive credits.

Mistral reads and composes. Elasticsearch finds the vocabulary. Application code checks every word.

## Quick start

Requires **Python 3.11+**. There are no runtime package dependencies.

```sh
git clone https://github.com/Paradox560/nyc-cut-up-machine.git
cd nyc-cut-up-machine
python3 -m cutup --demo
```

Open **http://127.0.0.1:8765**. Demo mode uses explicitly synthetic vocabulary and fixed compositions for each form. It makes no API calls and does not pretend to interpret a freeform brief or use historical evidence.

## Connect the real services

```sh
cp .env.example .env.local
# Fill in the three credentials locally, then:
python3 -m cutup check
```

| Setting | Value |
| --- | --- |
| `MISTRAL_API_KEY` | A Mistral API key with inference access |
| `ELASTICSEARCH_URL` | The Elasticsearch HTTPS endpoint, not a Kibana URL or Cloud ID |
| `ELASTICSEARCH_API_KEY` | An encoded API key with create-index, document write, read, and index metadata permissions for this project's index |
| `ELASTICSEARCH_INDEX` | Defaults to `nyc-cut-up-machine`; use a dedicated index |
| `MISTRAL_CHAT_MODEL` | Defaults to `ministral-3b-2512`; choose a model your account has inference quota for |
| `MISTRAL_OCR_MODEL` | Defaults to `mistral-ocr-latest` |
| `MISTRAL_EMBED_MODEL` | `mistral-embed` (1,024 dimensions) |
| `MISTRAL_VOICE_ID` | Optional saved Mistral voice; enables spoken compositions |

`.env.local`, downloaded images, corpus data, and generated work are ignored by Git. Credentials stay in the Python process and are never sent to the browser. Environment variables override the local file. Settings are reloaded on each web request.

### Load NYC photographs

The manifest contains verified Municipal Archives item records. Start small:

```sh
python3 scripts/ingest.py --limit 3 --download-only
python3 scripts/ingest.py --limit 3
python3 -m cutup
```

Open **Source drawer**. Inspect each image, correct the transcription, keep only clearly visible storefront words, and mark the source reviewed. Saving a review embeds the corrected text and writes it to Elasticsearch. Index all already-ingested sources with `python3 -m cutup index`.

The full manifest includes additional Manhattan storefronts with richer signage; increase `--limit` to ingest those. Review state is preserved on ordinary re-ingestion. The explicit OCR refresh option resets it. See [archive ingestion and attribution](docs/ARCHIVE.md) for details.

If your account has vision/chat quota but its OCR API is rate-limited, select the explicit vision-transcription path:

```sh
python3 scripts/ingest.py --limit 18 --transcription-method vision
```

This uses the configured vision-capable chat model. Sources retain the actual transcription method and model; the app does not call this OCR API output. Model listing access alone does not prove that the account has inference quota for every listed model.

For a custom collection, copy the schema in `data/seeds.json` and use `--manifest path/to/manifest.json`. Downloads are restricted to the Municipal Archives host, checked as JPEG/PNG, bounded in size, and requested politely. Images remain local, not in this source repository.

### Make a print

1. Describe the feeling or purpose: “a breakup letter that sounds like a shop closing.”
2. Choose poem, love letter, breakup letter, or manifesto.
3. **Cut it together** retrieves source vocabulary and composes with Mistral.
4. Click a word to inspect its photograph and source transcription.
5. Copy the words or export the print as SVG.

A small collection cannot express every request. The model makes the closest found poem using available words; it cannot invent missing connective words. Reusing an existing word is allowed. The archive supplies the vocabulary, not a claimed historical poem or message.

## How it works

```text
NYC Municipal Archives photographs
        ↓ Mistral transcription → visual review
Elasticsearch: source metadata + text + Mistral embeddings
        ↓ BM25 and vector search combined with RRF
Mistral: selects immutable word IDs from retrieved vocabulary
        ↓ strict local verification, one bounded repair attempt
Original source words → paper collage → clickable evidence / SVG
```

- **Search is essential:** live compositions retrieve vocabulary from Elasticsearch using both lexical and semantic ranking. It is not an incidental log store.
- **Provenance is enforced:** the model returns IDs, not prose. The server reconstructs words from source text. Unknown IDs, stale transcriptions, malformed output, or excess length are rejected.
- **Review is separate from code validation:** proving a word exists in OCR does not prove the OCR is right. Live UI compositions use reviewed sources only.
- **Snapshots survive edits:** each saved composition contains its source evidence at creation time. Later source corrections do not silently rewrite old prints.
- **No quiet fallback:** live provider failures produce errors. They do not turn into synthetic poems labeled as live output.
- **Optional voice:** Voxtral reads an existing verified composition when `MISTRAL_VOICE_ID` is configured. No browser TTS is substituted.

## Development

```sh
python3 -m unittest discover -s tests
node --check web/app.js
```

Tests cover provenance, invalid model output, source corrections, persistence, ingestion validation, API boundaries, and review/index synchronization. Tests do not require paid services; live service checks are explicit commands.

See [the three-minute demo script](docs/DEMO.md). The frontend is plain browser JavaScript and CSS; the backend uses Python's standard library. This is a local hackathon application, bound to loopback. Public deployment would need authentication, request limits, and a production HTTP server.

## Data and credits

Photographs: **1940s Tax Department photographs, Courtesy of the Municipal Archives, City of New York.** Each item also preserves its title, source URL, borough, block, and lot. Consult each archive record's rights information before redistributing images. The code repository contains metadata and source code, not a republished photograph collection.

The project is inspired by the hackathon's [tax-photo starter notebook](https://github.com/AvenueJ/elastic-mistral-hacknight/blob/main/nyc_tax_photos.ipynb). Historical record dates describe the collection; the app does not infer current businesses, ownership, or whether a building survives today.
