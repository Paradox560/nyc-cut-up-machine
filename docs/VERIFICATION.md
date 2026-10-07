# Verification record

Validated on October 7, 2026 against a local Python server, Mistral's hosted API, and Elasticsearch Serverless 9.6.0.

## Completed

- 106 automated tests pass. The suite uses isolated temporary storage and mocked paid services, with real localhost HTTP tests for request boundaries. Crop tests cover pixel bounds, image hashes, stale locations, exact matching, and explicit acceptance.
- JavaScript modules pass `node --check`.
- Real Mistral account authentication and `mistral-embed` requests succeed; embeddings contain 1,024 dimensions.
- Eight actual NYC Municipal Archives photographs were transcribed with `ministral-3b-2512`, visually checked by the development assistant, corrected conservatively, and indexed in the dedicated Elasticsearch index. Ambiguous lettering and foreground tax placards were omitted.
- 42 word occurrences across five photographs have visually accepted pixel rectangles. Seventeen came from Tesseract proposals and 25 were manually located. Blurred detections and rectangles containing substantial neighboring words were excluded. These accepted locations and original-image hashes are indexed alongside source text.
- Elasticsearch hybrid BM25/vector retrieval returns the indexed source evidence.
- Live compositions pass the local word-provenance validator and retain immutable source snapshots. The tiny starting vocabulary makes output deliberately fragmentary and limits how closely it can satisfy arbitrary briefs.
- Browser checks cover initial load, actual composition, source inspection, source-library access, SVG download, and a 390px mobile layout. No JavaScript errors or horizontal overflow were observed.
- A real browser request produced a verified 12-word photographic collage from two sources. Every live word was an SVG image crop with an explicit clip path and no visible text node. Selecting a word displayed an enlargement and the exact rectangle on the full original photograph.
- The source JPEG bytes matched their stored SHA-256 fingerprints, and the browser verified their decoded dimensions. A replay of the saved real response at 390px had no horizontal overflow or JavaScript errors.
- The exported SVG contains two byte-identical embedded source photographs reused by 12 clipped word viewports. It rendered visibly with every HTTP/HTTPS request blocked. The export keeps attribution and machine-readable crop provenance; no displayed poem word is a typeset text element.
- The supplied API credentials were checked against all Git blobs before publication; neither is committed. Only `.env.example` is tracked.

## Explicit limits

- The account's dedicated OCR models returned HTTP 429. The working dataset used the explicit **vision transcription** path, with that method and actual model recorded on every source. No claim is made that the dedicated OCR API completed these transcriptions.
- The event guide's Large 4 was not available under the supplied account, and Medium/Small inference was rate-limited. The user identified working quota for `ministral-3b-2512`; that model was verified and configured.
- Optional Voxtral speech is implemented but was not live-tested because no voice ID was supplied.
- This is a loopback-only hackathon app, not a publicly hosted multi-user service.
- Downloaded archive images, reviewed corpus, credentials, and generated prints stay in ignored local data. A fresh clone starts with the labeled synthetic demo or imports and reviews its own archive vocabulary.
