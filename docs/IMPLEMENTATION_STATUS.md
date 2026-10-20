# Implementation status — 20 October 2026

Status: substantial local pilot delivered; the final production solution is not complete. No deployment, cloud spend, production integration or physical camera validation has been performed.

## Delivered

| Plan area | Local implementation |
|---|---|
| P0 — baseline | Modular Vite/plain-JavaScript app, dark UI preserved, decoded artwork intake, search/export, conflict-aware import preview, legacy browser recovery and intake draft recovery |
| P1 — shared state | Python/FastAPI, PostgreSQL-compatible SQLAlchemy schema with SQLite development fallback, private content-addressed artwork, stable identities, named-user sessions, supervisor actions |
| P2 — production lifecycle | Sheet placements/rotation/sides, bounds/overlap checks, explicit release, allocation quantities, active pool, partial/final packing, cancellations, reprints, single-event reversals and append-only audit events |
| P3 — recognition baseline | Camera selection/capture or photograph upload, experimental automatic framing with visible outlines, optional four-corner rectification, configurable station product classes, basic quality checks, durable leased feature worker, versioned ORB cache, Hamming/RANSAC ranking, inlier evidence and explicit ambiguity |
| P4 — evaluation tooling | Separate candidate review/quantity confirmation, pool/allocation revision validation, held-out manifest runner with duplicate/reference-byte leakage checks; no claimed physical results |
| P5 — release preparation | Single-command development launcher, pinned dependencies, built container, same-origin static/API hosting, private-data denial in Vite, checksummed SQLite backup/restore and runbook |

## Evidence

- 23 API/domain/recovery/geometry/print-kit/draft-edit tests passed in the latest complete PostgreSQL run (PostgreSQL 17 in a dedicated local test container). Tests with physical-storage restore/auth use isolated SQLite where appropriate. PostgreSQL tests reset only an explicitly named `wdwp_test_` database.
- The complete 33-test suite also passed on Windows/SQLite and inside the Linux application container. The current container test run disabled pytest caching and passed without that cache warning. The TestClient dependency emits a deprecation warning about its HTTP transport.
- Browser: synthetic order upload/save, sheet creation and release, 40/100 manual packing, photo upload, ranked candidate review, separate packing of the remaining 60, and retirement of the completed allocation.
- A second independent browser session saw the same server-backed order and completed sheet. Text search and unsaved intake recovery across reload passed.
- Mobile viewport 390 × 844 had no horizontal overflow. Desktop/mobile screenshots are retained locally in ignored `output/playwright/`.
- Vite requests for the database, local environment file and archived Git bundle returned 403.
- JavaScript syntax checks, Python undefined/unused-name checks, production Vite build and whitespace checks passed. OpenCV reports version 5.0.0.
- Multi-stage app container built successfully on the local Podman runtime. Its 33-test runtime suite also passed; production deployment remains separate.

All matching browser/API checks above use synthetic artwork. Self-matching is useful for integration testing but does not establish accuracy on printed/camera-captured products. The evaluator rejects exact reference-byte leakage for held-out runs.

## Remaining work and release gates

| Gate | Required evidence / owner input |
|---|---|
| Physical corpus and station | Actual camera, mount/lighting, product-size choice and authorized printed samples; include the 50 near-identical names from the original concept |
| Recognition reliability | Held-out physical captures, distinguishing-region/OCR experiments as needed, unknown/ambiguous/glare/blur tests, numerical acceptance targets and operator trials |
| Capture geometry | Physical validation of automatic product framing and measured/calibrated station geometry; experimental outlines, manual corners and configured size classes are available now |
| Production ingestion | Representative MIS/ERP/imposition exports; confirmed sheet quantity, duplex, bleed and artwork-revision rules; adapter and migration validation |
| Scale | Production-sized active dataset, pagination/indexing, load/latency tests and review of the serialized workflow-write guard |
| Operations | Approved identity lifecycle, retention, monitoring/alerts and production recovery objectives; an isolated synthetic PostgreSQL restore drill passed |
| Deployment | Approved host, HTTPS/proxy settings, secrets and operating budget; production rollout and rollback rehearsal |

This status intentionally does not call every original phase complete. The repository contains a runnable local path through the main workflow and a conservative experimental matcher; the gates above determine when it can be used with real production work.


Additional evidence: [PostgreSQL restore drill](POSTGRES_RESTORE_DRILL.json) verifies restored images, export, audit events and a 37-packed/63-remaining allocation in a separate database and storage root. The generated synthetic print kit is in `data/evaluation-print-kit/` and can be regenerated using the runbook. No printing or physical photography was performed.


Continuation: draft editing, immutable released compositions and revision-checked release are verified by API tests and a browser scenario. See [the completion audit](COMPLETION_AUDIT.md) for the full requirement-by-requirement audit and remaining engineering work.


Artwork revision history, supervisor uploads, explicit version selection and immutable production bindings are now implemented. Schema version 2 includes transactional upgrade and guarded downgrade, verified on SQLite and PostgreSQL. The selected first physical pilot uses a phone camera and business cards; HTTPS access and actual device/corpus validation remain pending.

Browser continuation: uploading revision 2 for the synthetic order succeeded. The phone scan screen requests `capture="environment"` where supported. The browser check uses desktop emulation; it does not verify a phone's camera or permission behavior.

