# Archive ingestion and evidence

The manifest includes the three starter photographs referenced by the
[hackathon's NYC tax-photo notebook](https://github.com/AvenueJ/elastic-mistral-hacknight/blob/main/nyc_tax_photos.ipynb).
It also includes 15 photographs from the first page of the archive's
[Manhattan collection](https://nycrecords.access.preservica.com/uncategorized/SO_e6e79554-4227-414f-afc2-5f008fb9c96b/),
discovered using the folder documented in the event's
[scraper](https://github.com/AvenueJ/elastic-mistral-hacknight/blob/main/tax_photos_scraper.py).
Item metadata was checked against the Municipal Archives item pages on October 7,
2026. The Manhattan set covers South, Whitehall, Front, and Moore Streets, with
legible hotel, bank, shop, and office signs. Review transcriptions before admitting
their words to the composition vocabulary.

| Item | Borough | Block | Lot |
| --- | --- | --- | --- |
| [17–23 Victory Boulevard](https://nycrecords.access.preservica.com/uncategorized/IO_039ddc71-0796-4a01-9043-aae5b1cf2080/) | Staten Island | 1 | 1 |
| [453 Richmond Terrace](https://nycrecords.access.preservica.com/uncategorized/IO_02dbfda8-e39f-4254-b65f-23b8933201dd/) | Staten Island | 2 | 728 |
| [427 Richmond Terrace](https://nycrecords.access.preservica.com/uncategorized/IO_13d2ff2f-ae36-4405-a02e-0eec3cea1db0/) | Staten Island | 2 | 720 |

The 15 additional records and all item URLs are in `data/seeds.json`. All 18 item
records date the photograph collection to 1939–1941. The exact capture date of
each photograph is not asserted. Downloads for the Staten Island starter images
are 400 × 600 pixels; the Manhattan downloads are 2800 × 4200 pixels. No images
were upscaled or modified.

## Import

Run from the project root with Python 3.10 or newer. The importer uses only the
standard library and configuration from the ignored `.env.local` file.

```sh
# Download the three approved images, without calling Mistral or Elasticsearch.
python3 scripts/ingest.py --download-only

# Download all 18 manifest images without OCR costs.
python3 scripts/ingest.py --download-only --limit 18

# Mistral OCR, lexical extraction, and local corpus storage for the collection.
python3 scripts/ingest.py --limit 18

# Explicitly write the imported records and embeddings to Elasticsearch too.
python3 scripts/ingest.py --limit 18 --index

# If OCR is unavailable, explicitly use Mistral vision chat for transcription.
python3 scripts/ingest.py --limit 18 --transcription-method vision
```

OCR requires `MISTRAL_API_KEY`. Indexing also requires `ELASTICSEARCH_URL` and
`ELASTICSEARCH_API_KEY`. No key is needed for `--download-only`.

Downloads are cached under `data/archive/` and checked on reuse. Requests identify
the project and are spaced at least one second apart. Only HTTPS item/download
URLs at `nycrecords.access.preservica.com` are accepted; redirects are checked too.
Responses must contain a structurally valid JPEG or PNG, remain at or below 20
MiB and 50 million pixels, and have a compatible MIME type. The archive's generic
`application/octet-stream` MIME is allowed only after image validation. The
standard-library checks validate headers, boundaries, PNG checksums, and end
markers; they do not completely decode compressed image pixels.

Existing local OCR and review decisions are reused. `--refresh-ocr` deliberately
replaces them, incurs another OCR request, and resets review. A failed import
exits nonzero; earlier successfully stored records remain available so a rerun
can resume. Indexing uses source IDs and never asks to delete the entire index.
The source's `ocr_model` records the configured model identifier used for its OCR
request; aliases such as `mistral-ocr-latest` can resolve differently over time.
Every new transcription also records `transcription_method` and
`transcription_model`. Vision is an explicit alternative, never a silent fallback;
it asks for legible signage only and still leaves sources unreviewed. For existing
sources, add `--refresh-ocr` to replace a transcription with the selected method.

## Review before composition

Mistral OCR is a proposed transcription. It can misread blurred signs or generate
text that is absent from the photograph. Every newly imported source therefore
has `reviewed: false` and must be checked in the source-review interface before
it becomes eligible for composition.

Keep only legible lettering visibly present in the image. Delete hallucinated
descriptions, Markdown labels, illegible guesses, and irrelevant assessment-board
numbers when curating storefront vocabulary. A source with no useful lettering
may remain in the archive without contributing words. The item's address,
borough, title, and attribution are metadata, and must never be added to the
composition vocabulary merely because they describe the photograph.

The mechanical guarantee is that every composed word maps to a reviewed source
transcription. This is not automated proof that OCR matches a photograph, nor
does a photographic citation provide a precise bounding box around a word.

## Expand the manifest

Copy `data/seeds.json`, append individually selected Municipal Archives items,
and pass `--manifest path/to/manifest.json --limit 20`. Each source requires its
real `IO_…` identifier, catalog title, borough, block, lot, item page URL, download
URL, and item-specific attribution. Use strings for block and lot identifiers.
The item and download URLs must refer to that same identifier. Empty manifests,
duplicate IDs, unknown hosts, and malformed records are rejected before download.

Do not substitute fictional word banks as if they were archive OCR. For a useful
creative demo, select photographs with clear storefront signs and curate enough
distinct lettering to support the desired writing style.

## Attribution and reuse

Every record retains the item-specific credit recommended by the event notebook:

> [Item Name], 1940s Tax Department photographs, Courtesy of the Municipal Archives,
> City of New York.

The photographs are not bundled in the Git repository. The code's software
license does not license these archival images. Consult the rights information
on each linked archive item and the archive's current publication/reproduction
terms for the intended use; this project does not assert that all images are
public domain or licensed under Creative Commons. Preserve source links and
attribution when presenting or exporting work.
