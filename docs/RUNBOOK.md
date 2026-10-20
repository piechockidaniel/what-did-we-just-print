# Local development and deployment runbook

## Local startup

From `H:\Active Solutions\what did we just print`:

```powershell
uv venv .venv
uv pip install --python .venv\Scripts\python.exe -r requirements.txt
npm ci
npm run dev
```

`npm run dev` starts the loopback API on port 8000, the feature worker, and Vite on port 5173. Stop with Ctrl+C. If another instance is using those ports, stop that instance first; the launcher does not terminate unrelated processes. To run separately use `npm run api`, `npm run worker`, `npm run dev:ui` in three terminals.

Development mode explicitly uses the automatic identity `local-developer`. The banner labels it. This mode is for the current computer only; do not expose Vite or the development API to a network. Data is shared across browser sessions through SQLite in `data/production.db`, with private originals in `data/artwork/`, descriptors in `data/features/` and captured images in `data/captures/`. `PRINT_DATA_DIR` changes the storage root; `DATABASE_URL` can select PostgreSQL. Keep one private-storage root shared by API and worker.

`npm run check`, `npm run test:api` and `npm run build` verify JavaScript syntax, workflow/recognition plumbing and production bundling. `npm run preview` previews the bundle on port 4173 with the API still running. It is not a production server.

## First workflow

1. Add customer/order and artwork variants, including a destination for each. Save the order. Feature preparation runs in the background; refresh to see ready/failed states.
2. Open Production. Register a uniquely named sheet, its dimensions and impressions. Select a variant, X/Y and rotation, and add each placement. Save the draft.
3. Use Edit draft to correct a saved composition or impressions before release. Save or cancel edits first; then verify quantities and release the reviewed revision. A stale browser cannot overwrite or release a changed draft. Each variant allocation receives impressions × its placements. The current starter handles each variant side separately; linked duplex products need an agreed upstream schema before production use.
4. Use manual independent identification, or open Scan station and upload a photo/start a camera. Optional four-corner input rectifies perspective. Station profiles constrain configured product-size classes; they are not physical calibration.
5. Inspect candidates and differing names/destinations. Confirm the allocation with an explicit reason, then separately enter packed quantity. Feature ratios are not probabilities. A matching image never packs units automatically.
6. Partial packing leaves remaining units active. Completion retires that allocation. Reprints create new draft sheets. Supervisors can cancel remaining units and reverse a packing event with reasons; history remains intact.

## Catalog migration

Export the previous app's JSON from its original browser origin. Choose Import catalog JSON, inspect the preview and confirm. Identical UUID/content records are skipped; conflicts reject the entire import. Existing UUIDs, original images and destinations survive. Recover browser catalog reads only the current origin's legacy `print-reference-desk` IndexedDB; it never clears legacy records. Draft intake uses a separate IndexedDB and recovers after reload where storage is available.

Limits: 10 MB per image, 20 megapixels after decoding, 50 variants per order, 80 MB request body. Split large catalog imports into multiple files. This initial JSON transfer is intentionally bounded; a future streaming artwork importer is needed for bulk production ingestion. Current catalog/jobs endpoints return the full local pilot dataset; production-scale pagination and retrieval indexing remain rollout work.

Sheet JSON matches this example (replace the variant UUID):

```json
{
  "number": "SHEET-001",
  "widthMm": 320,
  "heightMm": 450,
  "impressions": 100,
  "placements": [
    { "variantId": "actual-variant-uuid", "x": 0, "y": 0, "rotation": 0, "side": "front" }
  ]
}
```

The server rejects out-of-bounds, overlapping same-side placements, missing variants and wrong sides. There is no PDF/imposition parser in this starter.

## Backup and restore

Catalog export is an artwork/order interchange file, not a backup of allocations, scans or history. For SQLite, stop API/worker for a conservative snapshot and use a new destination outside the data root:

```powershell
.venv\Scripts\python.exe -m server.manage backup H:\Backups\wdwp-unique-snapshot
.venv\Scripts\python.exe -m server.manage verify-backup H:\Backups\wdwp-unique-snapshot
.venv\Scripts\python.exe -m server.manage restore H:\Backups\wdwp-unique-snapshot H:\Backups\wdwp-restore-drill
```

Backup hashes each file and checks SQLite integrity and artwork references. Restore requires a new directory and does not overwrite live data. For a drill, set `PRINT_DATA_DIR` to the restored directory in a separate shell, unset DATABASE_URL if it points to the old SQLite file, and run an isolated API port. Verify order images, quantities and history before considering any cutover. Original data stays intact. Tests include a restore to another directory with the original artwork made unavailable.

For PostgreSQL, stop writes/worker, take a `pg_dump` and matching private-data snapshot, and restore into a separate database/storage root. The SQLite backup command refuses PostgreSQL. A production PostgreSQL restore drill and agreed recovery objectives remain release gates.

## Authentication and deployment preparation

The normal API defaults to authentication required (`PRINT_DEV=0`). Create named users privately; passwords are prompted and hashed:

```powershell
.venv\Scripts\python.exe -m server.manage create-user supervisor-name --role supervisor
```

Roles: operators create/read orders and sheets, release work, review scans and pack. Supervisors/admins additionally register stations, retry failed preparation, cancel allocations and reverse packing. Cookies are HTTP-only, same-site strict and secure outside development, with eight-hour expiry. Serve production over HTTPS. Set PRINT_ORIGIN to the exact approved browser origin and PRINT_ALLOWED_HOSTS to approved hostnames. Proxy the app and API under the same origin. Writes require the custom client header and reject unrelated origins. Add gateway rate limiting and operational identity/account lifecycle controls before network rollout.

The Dockerfile builds Vite and serves only `dist/` through the API; originals stay outside static hosting. `compose.yaml` prepares PostgreSQL, app and worker with private volumes. It binds the app to host loopback port 8080 for a separately approved HTTPS proxy. It requires private database credentials and an approved public origin; `.env.example` contains placeholders only. The database URL password must be URL-encoded. Do not commit real settings. No production deployment, DNS or account changes have been performed.

On this Windows Podman setup, image builds required `podman build --network host -t localhost/wdwp-app:local .` because the default build network could not reach npm. This is a local build-network observation, not a required setting for other hosts. Runtime deployment must retain its normal isolated service network.

## Recognition evaluation

The installed baseline uses OpenCV 5, ORB/Hamming correspondence, RANSAC geometric verification, basic exposure/blur/feature gates, versioned cached features and top-five candidates plus all allocations sharing the leading artwork. It always requires operator review, including a single candidate. It includes experimental quadrilateral boundary detection with a visible outline and manual-corner fallback. It does not perform OCR, calibrated name discrimination, adaptive zoom or validated physical-size estimation.

Fill a manifest using `evaluation-manifest.example.json`, with separate physical capture sessions and authorized samples. Then run:

```powershell
.venv\Scripts\python.exe -m vision.evaluate path\to\manifest.json --output path\to\new-report.json
```

The runner rejects reference-byte leakage, duplicate captures and paths outside the manifest directory. It measures retrieval, unknown rejection, ambiguity and latency. It does not infer physical provenance or operator acceptance accuracy. A camera/printed corpus, held-out physical runs and agreed error/review/latency targets are still needed. Do not treat synthetic self-matching as physical-print evidence.

## Operations and rollback

- Health: `/api/health` checks database access; Production shows feature jobs and failures. A dedicated worker heartbeat/alerting system and production monitoring backend are not yet installed.
- Failed preparation: inspect the error, correct artwork by creating a new reference, or retry as supervisor. Worker leases expire after five minutes; unfinished jobs recover with at most three attempts. Startup reconciles missing/current-version caches for rebuilding.
- Stale scan: any allocation release/packing/cancellation/reversal changes the pool revision. Repeat the scan before packing. Manual packing still uses allocation revisions and quantity checks.
- Outage: no successful write is assumed without a server response. Retry keys protect packing/release. Intake drafts recover locally where storage is available. Refresh before continuing work.
- Rollback: retain the prior image/source and matching database/private-storage snapshot. Current schema is version 2. Startup transactionally upgrades version 1 and rejects unknown versions. Stop writers and make a verified backup before running upgraded code. Inspect with `python -m server.manage schema-version`; explicitly upgrade with `python -m server.manage migrate --target 2`. A downgrade with `python -m server.manage migrate --target 1 --downgrade` is allowed only before any second artwork revision exists. Otherwise restore a matching prior backup into a separate location; never discard revision history to force a downgrade.
- Secrets and customer data: `data/`, `.env*`, captures and generated test output are ignored. Vite blocks private data, archives and local settings; production serves only built assets. Set retention and access policies with the owner before real customer data is imported.

Release requires owner review of physical evidence, quantities/duplex rules, dataset scale, access/retention, PostgreSQL recovery, approved deployment and operating costs. These gates are separate from the passing local checks.

## Synthetic print kit for the physical pilot

A generated kit is available locally in `daa/evaluation-print-kit/print.html`. It contains 50 near-identical fictional names, one intentionally duplicated artwork assigned to another destination, three unknown designs, catalog JSON and six sheet JSON files. It was not imported into the live workspace. Generate a fresh kit with:

```powershell
.venv\Scripts\python.exe scripts\generate_print_kit.py data\new-evaluation-kit
```

Open the HTML, print at actual size, measure the 90 × 50 mm cards, cut them, and collect separate camera captures. The included manifest is a template; the kit contains no physical photographs and establishes no recognition accuracy. Reference PNGs must not be used as held-out test captures. Names and customer details are fictional.

For a Compose deployment, bootstrap users inside the app container (`docker compose exec app python -m server.manage create-user operator-name --role operator`) so the command uses the same PostgreSQL URL and private-storage configuration. Running the CLI on the host without those environment settings would address the local SQLite database instead.

## Artwork revisions

Open an artwork's revision history to inspect originals. Supervisors can upload a changed image with a reason. New placements default to the current revision; the composition editor also permits an explicit historical revision. Saved drafts, released allocations and reprint drafts preserve their original version until explicitly edited. Matching uses the allocation's pinned image. Catalog export contains current artwork only; use a complete database/private-storage backup to preserve revision history.

## Selected physical pilot: phone camera and business cards

The user selected this setup on 20 October 2026. The synthetic kit uses 90 × 50 mm cards; measure printed dimensions before evaluation. Use the rear camera, one flat card, even lighting and a fully visible boundary. The upload control requests rear-camera capture on supporting phones; browser behavior varies. Live capture requests the rear camera by default and stops when the station is left.

A phone's localhost refers to the phone itself. The current loopback development server is accessible only on this computer. Phone live capture requires an approved HTTPS host trusted by the phone, normal named-user authentication and matching origin/host configuration. Network exposure, certificates and deployment have not been performed. Until that setup is approved, capture photographs on the phone and transfer them for local upload/evaluation. Record phone/browser, lighting, distances and capture session in the evaluation manifest; no physical validation is claimed.
