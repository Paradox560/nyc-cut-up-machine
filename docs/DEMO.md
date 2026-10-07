# Three-minute hackathon demo

The promise: **write a new message using actual pieces of historical NYC photographs, then reveal exactly where every word or letter was cut.**

## Before presenting

- Follow the setup and import instructions in the README. Keep credentials in ignored local configuration.
- The prepared local corpus has 59 photographs, 51 reviewed sources (50 with nonempty text), 105 accepted word crops, and 31 letter crops. The photographed alphabet covers A–Z; supported additional characters are `!`, `'`, `-`, `0`, and `5`.
- Review transcriptions against the originals, inspect word and letter crops, and index accepted evidence. Rehearse live Mistral embeddings, Elasticsearch retrieval, and a complete composition.
- Start with `python3 -m cutup --port 8765`. A fresh clone must import and review its own archive data; images and the prepared corpus are ignored local files.
- The explicit `--demo` option uses invented sample words and fixture responses. Label it as synthetic when presenting it.

## 0:00–0:25 — Set the constraint

“What if New York could write you a message using the letters it put on its buildings? This machine turns an archive into a photographic alphabet.”

Show an imported photograph, its archive attribution, and one reviewed storefront word. Explain that each usable word or letter has an accepted rectangle in the original image.

## 0:25–1:10 — Make an exact custom message

Choose **Make it a custom** and enter the live-tested message with its line break:

```text
Stay weird New York!
Make room for quixotic joy
```

“Your words stay yours. Mistral embeds the request, and Elasticsearch retrieves photographic words and letters. The app prefers whole photographed words and spells missing words using individually verified letter cutouts.”

Custom mode preserves the input and line breaks without a chat-model rewrite. Visible letter case follows the old signs; copying the message preserves its exact text. Each displayed fragment is an actual photo crop. Unsupported characters produce an explicit error instead of a font substitute.

## 1:10–1:50 — Prove a letter

Click a fragment. Show its enlarged cutout and outlined rectangle in the full photograph. Inspect another letter from a different source. The grain, weathering, and different historical letterforms should remain visible.

“Every fragment is bound to an image fingerprint and exact coordinates. We can point back to the evidence.”

The backend rejects unknown crop IDs, stale source data, changed image bytes, missing coordinates, and unsupported characters. Visual review establishes what a crop depicts; neither Mistral nor the app redraws its letters.

## 1:50–2:30 — Let Mistral write

Choose a generated form such as a poem or love letter and give it a short brief: “A love letter to a city that stays strange.”

“Mistral writes the message. Elasticsearch finds the archive fragments that can physically spell it. The same provenance checks apply.”

With a reviewed letter drawer, generated writing can use new words assembled from real photographed characters. Without it, the original word-only constraint remains. Describe only the flow exercised in the current run.

## 2:30–3:00 — Export the evidence

Export the SVG poster and open it offline. Source photograph bytes, crop geometry, credits, and provenance travel with the artwork. A 390px mobile view and offline SVG rendering have been checked.

“Mistral reads, embeds, and writes. Elasticsearch makes a growing archive searchable. The print is made from the city's actual photographed marks.”

Optional voice features should be presented only after a separate successful live rehearsal.

## Honest fallback

If a provider fails, say so and show a saved live result with its original evidence snapshot, labeled as saved. If none exists, use the labeled synthetic demo. Do not present a fixture as a current archive search.
