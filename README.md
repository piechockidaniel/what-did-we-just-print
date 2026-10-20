# What Did We Just Print, Man?

A web workspace for restoring cut print-job identity through reference artwork, active production sheets, candidate review and audited packing. Built with Vite and plain JavaScript, a Python/FastAPI API, SQLAlchemy and an OpenCV 5 feature worker. The UI retains the dark print-floor design, orange controls, registration marks and CMYK accents. The empty 24-slot reference grid is decorative.

## Run locally

From `H:\Active Solutions\what did we just print`:

```powershell
uv venv .venv
uv pip install --python .venv\Scripts\python.exe -r requirements.txt
npm ci
npm run dev
```

Open http://127.0.0.1:5173/. One command starts the API (8000), feature worker and Vite (5173), all for local development. The banner explicitly identifies the automatic local developer identity. Do not expose this development mode to a network. Existing browser-only records can be imported with a preview; they are never cleared automatically.

```powershell
npm run check
npm run test:api
npm run build
```

## Implemented local workflow

- Intake orders with original PNG/JPEG/WebP artwork, quantities, destinations and stable UUIDs. Recover unsaved intake drafts after reload where browser storage is available.
- Shared server persistence across browser sessions; PostgreSQL support and a SQLite local fallback. Originals use private content-addressed storage.
- Preview/import/export the original catalog format, preserving UUIDs and images; skip identical imports and reject conflicts atomically.
- Register production sheets with dimensions, impressions, placements, rotation and sides. Validate bounds/overlaps and explicitly release allocations.
- Track partial packing, remaining quantities, completion, reprints, cancellations, reversals and audit history. Revision checks and idempotency keys protect concurrent and repeated requests.
- Capture through a browser camera or upload a photo; optionally supply four corners for perspective correction. Configure station size classes and restrict searches to a production sheet.
- Inspect artwork history and upload revisions as a supervisor. Saved compositions and allocations keep their original artwork; new placements can select a specific revision.
- The selected first physical pilot uses a phone camera and business cards. Rear-camera capture is requested where supported; see the runbook for HTTPS access and physical evaluation requirements.
- Prepare/cache ORB descriptors in a separate durable worker. Compare with Hamming distance and geometric verification, showing ranked candidates, inlier counts/ratios and point evidence.
- Require operator identification review and a separate packing quantity confirmation. Shared artwork remains ambiguous; stale scans are rejected when the active pool changes.
- Named-user sessions outside development, supervisor controls, checksummed SQLite backup/restore and a container deployment configuration.

## Validation boundaries

This is a local pilot implementation. Synthetic API/browser checks establish workflow behavior, not real-print recognition accuracy. The matcher always requires review; ratios are not probabilities. Near-identical-name discrimination, OCR, automatic product boundaries, physical camera calibration, adaptive zoom and whole-stack validation are not established. Linked duplex products, upstream MIS/ERP integration, production-scale indexing/pagination, monitoring/retention policy and final deployment need further work and owner input.

The previous private Sites deployment remains the historical browser-only prototype. A static `dist/` upload alone cannot run the new shared workflow: deploy the API and worker as described in the runbook. No production publishing, DNS changes or cloud spending were performed.

## Documentation

- [Runbook](docs/RUNBOOK.md): startup, migration, sheet JSON, authentication, backup/restore, deployment and evaluation.
- [Implementation status](docs/IMPLEMENTATION_STATUS.md): verified evidence and remaining release gates.
- [Final solution plan](docs/FINAL_SOLUTION_PLAN.md): agreed direction, phases, decisions and acceptance criteria.
- [Concept](docs/CONCEPT.md): original production lifecycle and recognition requirements.
- [API contracts](docs/API.md): workflow endpoints and concurrency rules; live OpenAPI at `/docs` on the API.

Edit `src/`, `server/` and `vision/`; `dist/` is generated. Dependency versions are recorded in `package-lock.json` and `requirements.txt`. The original static prototype is retained in `archives/prototype-before-vite/`. Keep private data, local settings, customer artwork and credentials outside source control.

