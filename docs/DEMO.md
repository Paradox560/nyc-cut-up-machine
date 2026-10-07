# Three-minute hackathon demo

The promise: **write something new with actual pieces of historical NYC storefront photographs, and reveal exactly where every word was cut.**

## Before presenting

- Use the setup and import instructions in the repository README. Keep credentials in local configuration; close terminal tabs that might expose them.
- Import a small set of actual NYC tax photographs with source links and attribution. Review and correct OCR against each photograph before approving its vocabulary. Choose enough legible storefronts to support the writing prompt.
- Run word localization, inspect the crop contact sheet, and accept only correctly framed words before indexing. Words without locations cannot appear in a live print.
- Index the approved sources and verify the configured Mistral and Elasticsearch connections. Rehearse the complete live search and composition once; service access alone does not establish a working demo.
- Inspect the vocabulary before choosing a prompt. A narrow historical corpus may simply lack the words for a request; that limitation is part of the creative constraint.
- Use synthetic sample mode only for explaining the interface or a clearly announced fallback. Its vocabulary is invented, its composition is a fixture, and it does not demonstrate a live service integration or archival evidence.

The local launch command is `python3 -m cutup --port 8765`. Start an initial import with `python3 scripts/ingest.py --limit 3`, review the imported text in the interface, and use `python3 -m cutup index` when indexing the local corpus is required. For an explicitly synthetic presentation, launch with `python3 -m cutup --port 8765 --demo`. See the README for prerequisites and current command details.

## 0:00–0:25 — Set the constraint

“What if New York could write you a breakup letter using only the words it put on its buildings? This machine turns an archive into a vocabulary. Every word has to come from a reviewed photograph.”

Show an actual imported photograph, its archive attribution, and the corrected storefront text. Explain that transcription and word locations are reviewed; the composer can use only words with accepted photograph crops.

## 0:25–1:10 — Retrieve and compose

Request a breakup letter, poem, or other supported form using a prompt suited to the imported vocabulary.

“Mistral embeds the request. Elasticsearch retrieves storefront vocabulary and crop coordinates using semantic and text search. Mistral selects exact words from that vocabulary. Application code resolves their IDs, verifies the original photographs, and cuts out the actual pixels.”

Show the retrieved sources, then the composition. Describe only the flow visibly exercised by this run. Do not describe a synthetic fallback as a live response.

## 1:10–1:50 — Prove a word

Click an output word. Show the enlarged photo cutout, then its outlined rectangle in the full photograph. Open a second word from another photograph to demonstrate that the result combines actual photographic fragments. The source image's original grain and lettering should be visible in the print.

“The model selects evidence IDs. It cannot insert a more convenient word. We preserve the original spelling and allow reuse and rearrangement.”

Explain that unknown IDs, superseded transcription, missing crop coordinates, and changed image bytes are rejected. Visual review establishes that a crop spells the intended word. The app does not regenerate or typeset the live collage's words.

## 1:50–2:30 — Change the writing brief

Try a second supported form or tone: “Make this a declaration of love.” Keep the same constraints. If the corpus cannot express the request, acknowledge the missing vocabulary and show how importing more photographs expands the instrument.

If voice is configured and rehearsed, demonstrate the supported audio feature briefly. Otherwise keep the presentation focused on the verified text workflow.

## 2:30–3:00 — Explain why both services matter

“Mistral reads the photographs, embeds the meaning, and composes with constrained selections. Elasticsearch turns a growing city archive into retrievable vocabulary. The result is creative writing with inspectable evidence.”

Export the SVG poster and show that its photographic cutouts remain visible offline: the original image bytes and their crop coordinates are embedded. End on the composition and one visible source photograph. Present only capabilities exercised in the current build; describe untested voice or expanded archive features as future work.

## Honest fallback

If an external service fails, state the failure and show a previously saved live result with its original evidence snapshot, if available. Label it as a saved result. If none is available, show the synthetic sample and say: “This demonstrates the interaction; these are invented sample words and no live archive search is occurring.” Never substitute a fixture while leaving a live-data claim onscreen.
