# Verification record

Validated on October 7, 2026 against a local Python server, Mistral's hosted API, and Elasticsearch Serverless 9.6.0.

## Completed

- 156 automated tests pass, including upstream-failure and custom-lettering edge cases. The suite uses isolated temporary storage and mocked paid services, with real localhost HTTP tests for request boundaries. Crop and glyph tests cover pixel bounds, image hashes, stale locations, exact matching, explicit acceptance, character-coordinate orientation, and rejection of mismatched word segmentation.
- JavaScript modules pass `node --check`.
- Real Mistral account authentication and `mistral-embed` requests succeed; embeddings contain 1,024 dimensions.
- The merged local corpus contains 59 photographs: 58 NYC Municipal Archives tax photographs and one Library of Congress photograph of Jack’s storefront in Far Rockaway, Queens. Fifty-one sources have been visually reviewed; 50 contain nonempty transcriptions eligible for indexing. Municipal Archives text uses the explicit `ministral-3b-2512` vision path; the LOC text was transcribed directly from the photograph.
- 105 word crops and 31 letter crops have accepted original-image rectangles. The letter drawer covers A–Z plus `!`, `'`, `-`, `0`, and `5`. Every accepted location is bound to the original image hash. Uncertain lettering, false detections, and poorly framed crops were omitted.
- Elasticsearch hybrid BM25/vector retrieval returns the indexed source evidence.
- Live compositions pass provenance validation and retain immutable source snapshots. Whole-word crops are preferred; missing words can be assembled from verified character crops. Unsupported characters fail explicitly, with no typeset substitution.
- Live custom composition preserved the exact text and line break in `Stay weird New York!\nMake room for quixotic joy`. Custom mode uses Mistral embeddings and Elasticsearch retrieval without a chat-model rewrite. Original photographed case may differ visually; copied text preserves the input.
- Browser checks cover initial load, actual composition, source inspection, source-library access, SVG download, and a 390px mobile layout. No JavaScript errors or horizontal overflow were observed.
- The earlier word-only browser check produced a verified 12-word photographic collage from two sources. Every live word was an SVG image crop with an explicit clip path and no visible text node. Selecting a word displayed an enlargement and the exact rectangle on the full original photograph.
- The source JPEG bytes matched their stored SHA-256 fingerprints, and the browser verified their decoded dimensions. A replay of the saved real response at 390px had no horizontal overflow or JavaScript errors.
- The earlier word-only export contains two byte-identical embedded source photographs reused by 12 clipped word viewports. It rendered visibly with every HTTP/HTTPS request blocked. The export keeps attribution and machine-readable crop provenance; no displayed poem word is a typeset text element.
- The custom lettering workflow was also checked in a mobile layout and as an offline SVG with its photographic fragments intact.
- The supplied API credentials were checked against all Git blobs before publication; neither is committed. Only `.env.example` is tracked.

## Explicit limits

- The account's dedicated OCR models returned HTTP 429. The working dataset used the explicit **vision transcription** path, with that method and actual model recorded on every source. No claim is made that the dedicated OCR API completed these transcriptions.
- The event guide's Large 4 was not available under the supplied account, and Medium/Small inference was rate-limited. The user identified working quota for `ministral-3b-2512`; that model was verified and configured.
- Optional Voxtral speech is implemented but was not live-tested because no voice ID was supplied.
- This is a loopback-only hackathon app, not a publicly hosted multi-user service.
- Downloaded archive images, reviewed corpus, credentials, and generated prints stay in ignored local data. A fresh clone starts with the labeled synthetic demo or imports and reviews its own archive vocabulary.
