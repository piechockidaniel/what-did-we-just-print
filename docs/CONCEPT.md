# What Did We Just Print, Man?

Design snapshot: 19 October 2026. Current implementation: reference intake only.

## Problem

Offset printing combines orders on sheets. Cutting removes sheet-level identity. Finishing and logistics operators need to recover each product's order and destination from its artwork, including variants differing only by a name.

## Production lifecycle — planned

Register sheet composition before release: sheet ID and size, placements, rotation, order/variant links, artwork versions, quantities and trim dimensions. Link original artwork or extract final-trim references from the composition, accounting for bleed.

Activate allocations at production release. Keep them searchable through finishing and packing. Retire them only when required quantities are confirmed packed. Partial packing leaves remaining work active; reprints and reopened work reactivate appropriate references. Preserve history. Retiring one sheet must not remove artwork used by another active order.

## Entities — proposed

- ArtworkVersion: immutable artwork hash, side, trim dimensions and image.
- Order / OrderVariant: customer identity, artwork links, quantities and destination.
- ProductionSheet / Placement: composition and variant allocations.
- ProductionAllocation: released, packed and remaining quantities.
- FeatureCache: descriptors and meaningful regions keyed by artwork hash and extraction configuration.
- Scan / CandidateMatch: capture, ranked evidence, decision and operator confirmation.

Artwork identity and order identity are separate. Identical artwork may belong to multiple orders.

## Recognition — proposed, not validated

Prepare references once: crop and normalize, locate meaningful content, extract descriptors and cache. Incrementally update the active search pool as orders enter and leave production; avoid recomputing unchanged artwork. Invalidate caches when artwork or preprocessing changes.

For live captures: locate product, correct perspective/rotation, assess blur/glare, extract compatible features, retrieve candidates and check geometric consistency. Binary descriptors with Hamming-distance comparisons are a starting approach to evaluate, not a final selected algorithm.

Shared logos and layouts can overwhelm small identifying differences. Evaluate distinguishing text/image regions and optionally OCR. Visually identical products cannot reveal different order IDs without production context. Scanning a top card cannot verify an entire stack.

## Ranked output

Return multiple candidates with reference previews, order/variant IDs, destinations, tentative matches, geometrically consistent matches, and a match ratio with an explicit denominator. Include distinguishing-region evidence when available. Scores are not calibrated probabilities.

Support suggested match, ambiguous candidates, insufficient evidence and unknown product. Initially require operator confirmation before updating packing records. Never silently choose a destination from tied artwork.

## Architecture and evaluation

Begin with one fixed camera station, stable lighting and one business-card size. Proposed competition architecture uses substantive OpenCV 5 analysis and a meaningful AWS matching/index component; neither integration exists yet. Verify current dependency compatibility before implementation.

Evaluate held-out physical captures separately from reference artwork. Include 50 similar names, distinct designs, identical artwork across orders, unknown products, rotation, skew, glare, blur, trimming variation and front/back differences. Measure wrong accepted matches, correct assignments, review rate, unknown rejection, top-k retrieval and latency. State dataset size, conditions and failures; self-matching artwork does not prove production reliability.

## Next implementation slice

After repository handoff: sheet registration, production allocations and active lifecycle, then camera capture and ranked matching. Migrate existing intake records explicitly. Test partial packing, shared artwork, reactivation, cache invalidation and ambiguity handling.
