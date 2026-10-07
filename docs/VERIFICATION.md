# Verification record

Validated on October 7, 2026 against a local Python server, Mistral's hosted API, and Elasticsearch Serverless 9.6.0.

## Completed

- 71 automated tests pass. The suite uses isolated temporary storage and mocked paid services, with real localhost HTTP tests for request boundaries.
- JavaScript modules pass `node --check`.
- Real Mistral account authentication and `mistral-embed` requests succeed; embeddings contain 1,024 dimensions.
- Eight actual NYC Municipal Archives photographs were transcribed with `ministral-3b-2512`, visually checked by the development assistant, corrected conservatively, and indexed in the dedicated Elasticsearch index. Ambiguous lettering and foreground tax placards were omitted.
- Elasticsearch hybrid BM25/vector retrieval returns the indexed source evidence.
- Live compositions pass the local word-provenance validator and retain immutable source snapshots. The tiny starting vocabulary makes output deliberately fragmentary and limits how closely it can satisfy arbitrary briefs.
- Browser checks cover initial load, actual composition, source inspection, source-library access, SVG download, and a 390px mobile layout. No JavaScript errors or horizontal overflow were observed.
- A final real browser request produced a verified 16-word print from three sources. Selecting a word opened the matching source photograph and archive record.
- The supplied API credentials were checked against all Git blobs before publication; neither is committed. Only `.env.example` is tracked.

## Explicit limits

- The account's dedicated OCR models returned HTTP 429. The working dataset used the explicit **vision transcription** path, with that method and actual model recorded on every source. No claim is made that the dedicated OCR API completed these transcriptions.
- The event guide's Large 4 was not available under the supplied account, and Medium/Small inference was rate-limited. The user identified working quota for `ministral-3b-2512`; that model was verified and configured.
- Optional Voxtral speech is implemented but was not live-tested because no voice ID was supplied.
- This is a loopback-only hackathon app, not a publicly hosted multi-user service.
- Downloaded archive images, reviewed corpus, credentials, and generated prints stay in ignored local data. A fresh clone starts with the labeled synthetic demo or imports and reviews its own archive vocabulary.
