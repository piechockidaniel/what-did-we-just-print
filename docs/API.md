# API workflow contracts

The API publishes OpenAPI at `/openapi.json` and interactive documentation at `/docs`. Browser requests use the Vite `/api` proxy in development and the same-origin API in deployment. JSON writes require `X-Print-Client: web`. Authentication is required outside explicit local development mode.

| Method / path | Purpose |
|---|---|
| GET `/api/health` | Database liveness and development-mode indicator |
| GET `/api/session` | Authenticated actor/role |
| POST `/api/login`, `/api/logout` | Named-user session lifecycle |
| GET, POST `/api/orders` | Shared catalog / validated order creation |
| GET `/api/artworks/{sha256}` | Authorized original artwork; private static paths are not exposed |
| GET `/api/variants/{id}/artwork` | Immutable artwork revision history |
| POST `/api/variants/{id}/artwork` | Supervisor revision upload with image, reason, key and expectedRevision |
| GET `/api/catalog/export` | Original schema-version-1 catalog with embedded original images |
| POST `/api/catalog/preview`, `/api/catalog/import` | Preview new/skip/conflict; atomic import with preserved IDs |
| GET, POST `/api/sheets` | Composition list / validated draft creation |
| PUT `/api/sheets/{id}` | Idempotent revision-checked editing of an unreleased draft |
| POST `/api/sheets/{id}/release` | Idempotent release into active allocations |
| GET `/api/allocations?active=true` | Active production with remaining quantities and feature readiness |
| POST `/api/allocations/{id}/pack` | Explicit audited packing, with optimistic revision guard |
| POST `/api/allocations/{id}/cancel` | Supervisor cancellation of remaining work |
| POST `/api/packing/{eventId}/reverse` | Supervisor reversal of a packing event, once only |
| GET `/api/history?limit=100&offset=0` | Paginated immutable audit events (max page 500) |
| GET `/api/jobs` | Durable reference-preparation state/errors |
| POST `/api/jobs/{id}/retry` | Supervisor retry of failed preparation |
| GET, POST `/api/stations` | Station profiles; creation requires supervisor |
| POST `/api/scans` | Rank compatible active allocations from a supplied capture |
| POST `/api/scans/{id}/review` | Confirm/reject a candidate with operator context; never changes quantities |

## Order migration

Orders preserve `id`, `orderNumber`, `customer`, `widthMm`, `heightMm`, optional `createdAt`, and `variants[]`. A variant has `id`, `name`, positive integer `quantity`, `destination`, original image data URL and `side`. Legacy file metadata is accepted, but image dimensions and MIME are verified by decoding the bytes. Each distinct image checksum has its own immutable artwork and versioned feature cache.

An exact create-order retry with the same ID/content returns the existing order without another audit event. Changed content under the same ID conflicts. Case-insensitive duplicate order numbers are rejected. Import previews identify conflicting IDs, numbers and variants both in the database and within the file; any conflict prevents the entire import. Original IndexedDB is never cleared.

## Quantities and retry behavior

Each placement can supply `artworkVersionId`; omission selects the current version when the draft is saved. The server validates variant ownership and pins the version. Sheet responses include an `artworkImages` preview map; this derived map is not part of the write body. Release creates separate allocations for distinct variant/version pairs. Updating current artwork never changes saved compositions or existing allocations. Catalog reads expose current revision metadata; schema-1 exports retain current images and omit that metadata. Complete revision history requires a full backup.

Sheet list entries include a `revision`. Edit with the complete sheet body plus `key` and `expectedRevision`; repeated identical edits return the original event. Invalid geometry, duplicate numbers and stale revisions leave the draft unchanged. Released compositions are immutable; use a reprint draft for new production.

Release body: `{ "key": "unique-request-uuid", "expectedRevision": 1 }`. The expected revision must match the reviewed draft. It defaults to 1 for initial-draft callers; edited drafts require their current revision explicitly. Every placement contributes one unit per impression to its variant's allocation. Draft sheets cannot contain same-side overlaps or out-of-bounds placements. The UI disables release while editing so unsaved changes cannot be mistaken for the released composition.

Packing body:

```json
{
  "key": "unique-request-uuid",
  "quantity": 20,
  "revision": 1,
  "scanId": null,
  "reason": "Independent manual identification at packing bench"
}
```

The client keeps the same key when retrying the exact operation after an uncertain response. Reusing a key for a different entity, quantity, revision or reason conflicts. A successful retry returns the original event. Revisions change after quantity mutations; stale or excessive packing returns HTTP 409 and leaves quantities unchanged. Server transactions and database constraints prevent negative or overpacked quantities. Workflow writes use a shared database guard, serializing the pilot's mutations across processes; production throughput must be measured before scaling this strategy.

For scan-based packing, `scanId` must identify a scan containing the allocation, its candidate revision must match, the active-pool revision must still match, and the latest review must confirm that allocation. A scan never authorizes an automatic packing update. Cancellation and reversal preserve audit history and require supervisor/admin access and a reason.

## Matching response

`POST /api/scans` accepts `image`, optional `sheetId`, optional `stationId`, and optional four pixel corners in TL/TR/BR/BL order. Station filtering uses configured product dimensions rather than inferring physical dimensions from pixels. The response includes scan ID, algorithm/configuration version, pool revision, quality measures, search filters, duration and candidate allocations with their revisions.

Candidates include artwork preview, variant/order/allocation identities, destination, remaining quantity, tentative matches, geometric inliers, inlier ratio, spatial coverage and normalized-capture point correspondences. A zero tentative-match denominator produces a null ratio. The baseline explicitly marks distinguishing-region evidence as not evaluated and requires review even for one candidate. Top-five output also includes every allocation sharing the leading artwork, so a truncated list does not hide identical-reference ambiguity.

Decisions: `review-required`, `ambiguous`, `unknown`, `insufficient-evidence`, or `unavailable`. They are experimental evidence categories, not probabilities or autonomous shipping decisions. A failed service returns an error, never a fabricated match. Newly released or retired allocations invalidate previous pool snapshots.

## Errors and limits

Validation: 422; authentication: 401; role/origin protection: 403; missing entity: 404; state/quantity/idempotency conflict: 409; request over 80 MB: 413. Decode limits are 10 MB and 20 megapixels per image. Full catalog/job lists are suitable for the local pilot; production dataset pagination and indexing are recorded in the rollout gates. The HTML client uses text nodes for user content.
