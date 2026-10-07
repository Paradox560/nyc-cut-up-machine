# Deploy StreetScript to Vercel

The Vercel deployment uses the same Python API and photographic evidence as the local workshop. `api/index.py` adapts the handler to HTTPS deployment hosts. Static files come from `public/`; the Python function reads the prepared corpus and original photo bytes from `deployment_data/`.

## Prepare and deploy

Start from a machine with the reviewed local corpus and original images already present:

```sh
python3 scripts/prepare_vercel.py --from-local
vercel link
# Add the required settings to the project's Production environment.
vercel env add MISTRAL_API_KEY production
vercel env add ELASTICSEARCH_URL production
vercel env add ELASTICSEARCH_API_KEY production
vercel deploy --prod
```

Enter credentials through Vercel's environment prompts or dashboard, never in source files or command arguments. The existing project can skip `vercel link` and environment setup when they are already configured.

Preparation validates source records and image fingerprints, selects reviewed nonempty sources, removes private preparation notes, and writes:

- `deployment_data/corpus.json`: the packaged source catalog.
- `deployment_data/archive/`: original JPEG/PNG bytes used for server validation.
- `public/`: web assets plus `public/archive/` photographs served statically.

The verified preparation contained **50 photographs, 105 word crops, and 31 letter crops**, with approximately **134 MiB** of original images. The Python bundle excludes `public/`, preventing duplicate originals inside the function. On Vercel, the build runs `python3 scripts/prepare_vercel.py` using the uploaded prepared bundle; it needs neither Tesseract nor raw ingestion data.

`deployment_data/`, `public/`, `.vercel/`, and local credentials remain ignored by Git. `.vercelignore` explicitly includes the prepared evidence for a CLI upload and excludes credentials, old compositions, tests, and raw preparation artifacts. **A GitHub-only automatic build cannot recover these ignored photographs or the reviewed corpus.** Deploy from the prepared local checkout until a separate artifact-download pipeline is implemented.

## Production settings

| Variable | Purpose |
| --- | --- |
| `MISTRAL_API_KEY` | Required for embeddings, generation, and moderation |
| `ELASTICSEARCH_URL` | Required HTTPS Elasticsearch endpoint |
| `ELASTICSEARCH_API_KEY` | Required access to the source index and create/read/write access to the composition index |
| `ELASTICSEARCH_INDEX` | Existing prepared source index; defaults to `nyc-cut-up-machine` |
| `MISTRAL_CHAT_MODEL` | Defaults to the verified `ministral-3b-2512` |
| `MISTRAL_EMBED_MODEL` | Defaults to `mistral-embed` |
| `CUTUP_PUBLIC_ORIGIN` | Optional exact HTTPS origin for a custom domain |
| `MISTRAL_VOICE_ID` | Optional; leave unset to keep speech disabled |
| `MISTRAL_TTS_MODEL` | Optional voice model; defaults to `voxtral-mini-tts-latest` |
| `CUTUP_MODERATION` | Defaults to enabled; `off` explicitly disables it and displays a warning |

Vercel supplies `VERCEL`, `VERCEL_URL`, and `VERCEL_PROJECT_PRODUCTION_URL`. The handler also accepts the platform's branch URL. Cross-origin API requests and unrecognized hosts are rejected. Update `CUTUP_PUBLIC_ORIGIN` before using a custom hostname.

## Persistence and boundaries

Vercel's function filesystem is read-only. Sources and photographs are packaged evidence; **source review is disabled on the hosted API**. Review or correct sources locally, reindex them, refresh the bundle, and redeploy.

Generated compositions are stored in Elasticsearch at `<ELASTICSEARCH_INDEX>-compositions`, separate from the archival search index. The first save creates this index with the composition object excluded from field indexing. Rearrange and speech can retrieve saved compositions across cold starts; prompts and source snapshots remain in this index until explicitly removed. No composition files are written to ephemeral function storage.

The hosted generator is public and has no application-level accounts or per-user quotas. Optional voice remains unavailable until a valid voice ID is configured. Missing evidence and provider errors are shown explicitly; production does not replace failed live output with synthetic lettering.

The adapter follows Vercel's [Python runtime](https://vercel.com/docs/functions/runtimes/python), [filesystem constraints](https://vercel.com/docs/functions/runtimes), and [deployment file allowlist](https://vercel.com/docs/deployments/vercel-ignore) documentation. `vercel.json` sets a 300-second function limit with Fluid compute and routes `/api/*` to the Python handler.

After deployment, check `/api/status`, generate a print, rearrange it, and compose a short custom message. Inspect a source and export an SVG to confirm that the static photographs and API deployment match.
