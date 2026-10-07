# NYC image sources and expansion

The original collection is already large enough to grow this project substantially. NYC Municipal Archives describes more than **720,000 photographs** in its 1940s tax collection. The prepared local corpus contains **59 downloaded photographs, 51 reviewed source records, 105 accepted word crops, and 31 accepted letter crops**. Fifty of the reviewed records contain nonempty transcriptions eligible for indexing. The manifest includes 58 Municipal Archives photographs and one Library of Congress photograph. Those counts describe different processing stages; a crop is a fragment of a photograph, not another photograph. The underlying collection is described in the [official finding aid](https://www.nyc.gov/assets/records/pdf/20200917_1940sTaxDepartmentPhotographs_REC0040_MASTER.pdf).

## Sources worth using

| Collection | Useful material | Scope and provenance | Current support |
|---|---|---|---|
| [NYC Municipal Archives 1940s tax photographs](https://www.archives.nyc/blog/2018/11/2/the-1940-tax-photosa-well-traveled-collection) | Painted storefront signs, window lettering, menus, shop names, rental notices | More than 720,000 images across the five boroughs; parcel identifiers, addresses, block/lot, and dates | Implemented importer; expanding the curated manifest is the quickest route to more real lettering |
| [NYPL Photographic Views of New York City, 1870s–1970s](https://digitalcollections.nypl.org/collections/photographic-views-of-new-york-city-1870s-1970s-from-the-collections-of-the-ne-2) | Other decades and streets, shopfronts, billboards, neighborhood scenes | Approximately 54,000 photographs and captioned versos in the collection description; not every physical image is necessarily a separate digitized item | Research candidate; requires an NYPL metadata/download adapter and item-level rights filtering |
| [Library of Congress WPA Posters](https://www.loc.gov/collections/works-progress-administration-posters/about-this-collection/) | Large, clear letterforms, punctuation, color, theater and civic vocabulary | 907 posters from 1936–1943 across multiple states; filter to NYC-associated works rather than labeling the entire collection NYC | Research candidate; useful when expanding beyond photographs into archival printed lettering |
| [Library of Congress NYC photographs](https://www.loc.gov/item/2018745577/) | Storefront signs and architectural documentation | The imported 1946 Jack’s Men’s and Boys’ Wear photograph is in Far Rockaway, Queens; the item identifies its creator, date, and rights advisory | One manually imported photo, transcribed from direct visual inspection without a Mistral call; automated LOC adapter not implemented |

The manually imported [Jack’s storefront](https://www.loc.gov/item/2018745577/) adds a clear J, independently verified by inspecting the sign. Its source record preserves the Gottscho-Schleisner Collection credit and the item’s ‘no known restrictions on publication’ advisory. The small 308×420 service image is sufficient for this large letter; it is not represented as a high-resolution scan. Its reproducible catalog/download metadata is in `data/loc-seed.json`.

For a concrete poster candidate, [New York, the wonder city of the world](https://www.loc.gov/item/2002720474/) is an NYC travel poster with a cataloged date, artist, and reproduction identifiers. Its page reports no known publication restrictions. This is a researched candidate, not an image already imported into the app.

## Rights and attribution

Municipal Archives' [terms](https://www.nyc.gov/site/records/historical-records/terms-and-conditions.page) distinguish noncommercial uses from commercial licensing and require acknowledgment for published uses. Preserve the item's name, collection, and Municipal Archives credit. The catalog also notes that third-party rights may exist; access to a download is not a blanket public-domain declaration.

NYPL explicitly offers a [public-domain subset](https://www.nypl.org/research/resources/public-domain-collections) for unrestricted reuse and high-resolution download. Filter by the item's designation; do not assume every item in the photographic collection belongs to that subset. At the Library of Congress, retain each item's rights advisory and creator credit rather than applying one rights label to all collections.

The repository contains catalog metadata and code. Downloaded image files, source transcriptions, generated results, and review artifacts remain local ignored data.

## Repeatable expansion

Discover a bounded page of official Municipal Archives metadata:

```sh
python3 scripts/dataset_discovery.py \
  --catalog-url 'https://nycrecords.access.preservica.com/uncategorized/SO_e6e79554-4227-414f-afc2-5f008fb9c96b/?pg=2' \
  --limit 16
```

The discovery script verifies item metadata, skips duplicate IDs and outtakes, spaces requests by one second, and writes only manifest entries. It does not download photographs or approve text. Existing import limits remain 20 MiB per image and 50 million pixels.

The expanded corpus was processed in bounded, disjoint batches, then merged after visual review. Its 31 accepted letter crops cover A–Z, the punctuation `!`, `'`, and `-`, and the digits `0` and `5`. Matching is case-insensitive; displayed letters retain the case, texture, and shape photographed on the original signs. Other punctuation and digits require additional verified crops.

For future batches, choose an explicit ingestion limit and check provider billing to understand actual usage. Existing sources are reused; avoid `--refresh-ocr` when preserving approved coordinates. The vision path uses the configured Mistral chat model and records its provenance; it does not silently claim to have used the dedicated OCR endpoint. Local Tesseract localization and visual crop review do not call Mistral. The prepared Municipal Archives transcriptions use `ministral-3b-2512`; the single LOC photograph was transcribed by direct visual inspection.

Compare each transcription with the actual photograph. Remove tax placards, invented annotations, partial names, and uncertain fine print. Keep unresolved photos unreviewed. Only then localize and inspect word or letter crops before indexing the accepted evidence. A small photograph may contribute no trustworthy words, even when a model returns a plausible sentence.

Track these metrics separately: manifest records, downloaded photographs, transcribed sources, reviewed nonempty sources, approved word crops, approved letter crops, and distinct supported characters. Prioritize legible signs that add missing letters, punctuation, useful connecting words, and visual styles. More downloads alone do not establish a larger usable vocabulary.
