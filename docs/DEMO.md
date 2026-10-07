# Three-minute hackathon demo

The promise: **write something new using only words visible in historical NYC storefront photographs, and trace every output word back to its source.**

## Before presenting

- Use the setup and import instructions in the repository README. Keep credentials in local configuration; close terminal tabs that might expose them.
- Import a small set of actual NYC tax photographs with source links and attribution. Review and correct OCR against each photograph before approving its vocabulary. Choose enough legible storefronts to support the writing prompt.
- Index the approved sources and verify the configured Mistral and Elasticsearch connections. Rehearse the complete live search and composition once; service access alone does not establish a working demo.
- Inspect the vocabulary before choosing a prompt. A narrow historical corpus may simply lack the words for a request; that limitation is part of the creative constraint.
- Use synthetic sample mode only for explaining the interface or a clearly announced fallback. Its vocabulary is invented, its composition is a fixture, and it does not demonstrate a live service integration or archival evidence.

The local launch command is `python3 -m cutup --port 8765`. Start an initial import with `python3 scripts/ingest.py --limit 3`, review the imported text in the interface, and use `python3 -m cutup index` when indexing the local corpus is required. For an explicitly synthetic presentation, launch with `python3 -m cutup --port 8765 --demo`. See the README for prerequisites and current command details.

## 0:00–0:25 — Set the constraint

“What if New York could write you a breakup letter using only the words it put on its buildings? This machine turns an archive into a vocabulary. Every word has to come from a reviewed photograph.”

Show an actual imported photograph, its archive attribution, and the corrected storefront text. Explain that OCR is fallible and the reviewed text is what the composer may use.

## 0:25–1:10 — Retrieve and compose

Request a breakup letter, poem, or other supported form using a prompt suited to the imported vocabulary.

“Mistral embeds the request. Elasticsearch retrieves relevant storefront vocabulary using semantic and text search. Mistral receives the retrieved word IDs and selects their order. Application code validates the IDs and renders the source words.”

Show the retrieved sources, then the composition. Describe only the flow visibly exercised by this run. Do not describe a synthetic fallback as a live response.

## 1:10–1:50 — Prove a word

Inspect an output word and follow its source attribution. Show its exact spelling in the corrected OCR and compare it with the image. Open a second word from another photograph to demonstrate that the result combines sources.

“The model selects evidence IDs. It cannot insert a more convenient word. We preserve the original spelling and allow reuse and rearrangement.”

Explain that an unknown ID, an ID from superseded OCR, or an unreviewed source causes rejection. These checks establish provenance to the reviewed text; the human comparison with the photograph establishes whether the OCR is accurate.

## 1:50–2:30 — Change the writing brief

Try a second supported form or tone: “Make this a declaration of love.” Keep the same constraints. If the corpus cannot express the request, acknowledge the missing vocabulary and show how importing more photographs expands the instrument.

If voice is configured and rehearsed, demonstrate the supported audio feature briefly. Otherwise keep the presentation focused on the verified text workflow.

## 2:30–3:00 — Explain why both services matter

“Mistral reads the photographs, embeds the meaning, and composes with constrained selections. Elasticsearch turns a growing city archive into retrievable vocabulary. The result is creative writing with inspectable evidence.”

End on the composition and one visible source photograph. Present only capabilities implemented and exercised in the current build; describe any future voice, export, or expanded archive features as future work.

## Honest fallback

If an external service fails, state the failure and show a previously saved live result with its original evidence snapshot, if available. Label it as a saved result. If none is available, show the synthetic sample and say: “This demonstrates the interaction; these are invented sample words and no live archive search is occurring.” Never substitute a fixture while leaving a live-data claim onscreen.
