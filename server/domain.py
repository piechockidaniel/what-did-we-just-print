"""Transactional workflow rules; clients never own production quantities."""

from collections import Counter
from datetime import datetime, timezone
import base64
from uuid import uuid4
from sqlalchemy import select, update, func
from fastapi import HTTPException
from .db import (
    orders,
    artworks,
    variants,
    sheets,
    allocations,
    events,
    jobs,
    scans,
    pool_state,
    artwork_versions,
    allocation_artwork,
)
from .storage import store_image, decode_image
import hashlib


def bump_pool(conn):
    conn.execute(
        update(pool_state)
        .where(pool_state.c.id == "active")
        .values(revision=pool_state.c.revision + 1)
    )


def pool_revision(conn):
    return conn.execute(
        select(pool_state.c.revision).where(pool_state.c.id == "active")
    ).scalar_one()


def uid():
    return str(uuid4())


def now():
    return datetime.now(timezone.utc).isoformat()


def fail(condition, message, status=409):
    if condition:
        raise HTTPException(status, message)


def record(conn, actor, kind, entity_id, payload, key=None):
    event = dict(
        id=uid(),
        kind=kind,
        entity_id=entity_id,
        actor=actor,
        created=now(),
        payload=payload,
        request_key=key,
    )
    conn.execute(events.insert().values(**event))
    return event


def existing_request(conn, key, kind, entity_id, payload):
    # Serializes workflow writes on both PostgreSQL and SQLite, including retries.
    # No process-local lock: multiple API processes share the same database guard row.
    conn.execute(
        update(sheets)
        .where(sheets.c.id == "__workflow_lock__")
        .values(impressions=sheets.c.impressions + 1)
    )
    previous = (
        conn.execute(select(events).where(events.c.request_key == key))
        .mappings()
        .first()
    )
    if previous:
        fail(
            previous["kind"] != kind
            or previous["entity_id"] != entity_id
            or previous["payload"].get("request") != payload,
            "Idempotency key was already used for a different operation",
        )
        return dict(previous)
    return None


def catalog(conn, include_images=False, root=None):
    latest = (
        select(
            artwork_versions.c.variant_id,
            func.max(artwork_versions.c.revision).label("revision"),
        )
        .group_by(artwork_versions.c.variant_id)
        .subquery()
    )
    output = []
    for order in conn.execute(
        select(orders).order_by(orders.c.created.desc())
    ).mappings():
        item = dict(
            id=order["id"],
            orderNumber=order["number"],
            customer=order["customer"],
            widthMm=order["width"],
            heightMm=order["height"],
            createdAt=order["created"],
            variants=[],
        )
        rows = conn.execute(
            select(
                variants,
                artworks.c.mime,
                artworks.c.path,
                artworks.c.width.label("pixelWidth"),
                artworks.c.height.label("pixelHeight"),
                artworks.c.state.label("status"),
                artwork_versions.c.id.label("artworkVersionId"),
                artwork_versions.c.revision.label("artworkRevision"),
            )
            .select_from(variants)
            .join(artworks, variants.c.artwork_id == artworks.c.id)
            .join(latest, latest.c.variant_id == variants.c.id)
            .join(
                artwork_versions,
                (artwork_versions.c.variant_id == variants.c.id)
                & (artwork_versions.c.revision == latest.c.revision),
            )
            .where(variants.c.order_id == order["id"])
        ).mappings()
        for variant in rows:
            image = f"/api/artworks/{variant['artwork_id']}"
            if include_images:
                from .db import ROOT

                base = root or ROOT / "data"
                image = (
                    f"data:{variant['mime']};base64,"
                    + base64.b64encode(
                        (base / "artwork" / variant["artwork_id"]).read_bytes()
                    ).decode()
                )
            item["variants"].append(
                dict(
                    id=variant["id"],
                    name=variant["name"],
                    destination=variant["destination"],
                    quantity=variant["quantity"],
                    image=image,
                    side=variant["side"],
                    artworkId=variant["artwork_id"],
                    artworkVersionId=variant["artworkVersionId"],
                    artworkRevision=variant["artworkRevision"],
                    pixelWidth=variant["pixelWidth"],
                    pixelHeight=variant["pixelHeight"],
                    status=variant["status"],
                )
            )
        output.append(item)
    return output


def create_order(conn, order, root, actor):
    if conn.execute(select(orders.c.id).where(orders.c.id == order.id)).first():
        from .schemas import Catalog

        preview = preview_import(conn, Catalog(schemaVersion=1, orders=[order]), root)
        fail(
            preview[0]["status"] != "skip",
            "Order ID already exists with different contents",
        )
        return {"id": order.id, "existing": True}
    fail(
        conn.execute(
            select(orders.c.id).where(
                func.lower(orders.c.number) == order.orderNumber.lower()
            )
        ).first(),
        "Order number already exists",
    )
    fail(
        len({v.id for v in order.variants}) != len(order.variants),
        "Duplicate variant IDs",
        422,
    )
    prepared = [
        (variant, store_image(root, variant.image)) for variant in order.variants
    ]
    conn.execute(
        orders.insert().values(
            id=order.id,
            number=order.orderNumber,
            customer=order.customer,
            width=order.widthMm,
            height=order.heightMm,
            created=order.createdAt or now(),
        )
    )
    for variant, art in prepared:
        fail(
            conn.execute(
                select(variants.c.id).where(variants.c.id == variant.id)
            ).first(),
            "Variant ID already exists",
        )
        if not conn.execute(
            select(artworks.c.id).where(artworks.c.id == art["id"])
        ).first():
            conn.execute(artworks.insert().values(**art, state="pending"))
            conn.execute(
                jobs.insert().values(
                    id=uid(),
                    artwork_id=art["id"],
                    state="pending",
                    lease_until=0,
                    attempts=0,
                )
            )
        conn.execute(
            variants.insert().values(
                id=variant.id,
                order_id=order.id,
                artwork_id=art["id"],
                name=variant.name,
                destination=variant.destination,
                quantity=variant.quantity,
                side=variant.side,
            )
        )
        conn.execute(
            artwork_versions.insert().values(
                id=uid(),
                variant_id=variant.id,
                artwork_id=art["id"],
                revision=1,
                created=now(),
                actor=actor,
            )
        )
    record(
        conn,
        actor,
        "order.created",
        order.id,
        {"number": order.orderNumber, "variants": len(prepared)},
    )
    return {"id": order.id}


def list_artwork_versions(conn, variant_id):
    fail(
        not conn.execute(
            select(variants.c.id).where(variants.c.id == variant_id)
        ).first(),
        "Variant not found",
        404,
    )
    return [
        {**row, "image": f"/api/artworks/{row['artwork_id']}"}
        for row in conn.execute(
            select(artwork_versions, artworks.c.state.label("readiness"))
            .join(artworks)
            .where(artwork_versions.c.variant_id == variant_id)
            .order_by(artwork_versions.c.revision.desc())
        ).mappings()
    ]


def revise_artwork(conn, variant_id, payload, root, actor):
    raw, _, _ = decode_image(payload.image)
    digest = hashlib.sha256(raw).hexdigest()
    request_data = {
        "artworkId": digest,
        "expectedRevision": payload.expectedRevision,
        "reason": payload.reason,
    }
    previous = existing_request(
        conn, payload.key, "variant.artwork.revised", variant_id, request_data
    )
    if previous:
        return previous
    current = list_artwork_versions(conn, variant_id)[0]
    fail(
        current["revision"] != payload.expectedRevision,
        "Artwork changed; refresh before uploading a revision",
    )
    fail(
        current["artwork_id"] == digest,
        "Image is identical to the current artwork; no new revision is needed",
    )
    artwork = store_image(root, payload.image)
    if not conn.execute(select(artworks.c.id).where(artworks.c.id == digest)).first():
        conn.execute(artworks.insert().values(**artwork, state="pending"))
        conn.execute(
            jobs.insert().values(
                id=uid(), artwork_id=digest, state="pending", lease_until=0, attempts=0
            )
        )
    identity = uid()
    conn.execute(
        artwork_versions.insert().values(
            id=identity,
            variant_id=variant_id,
            artwork_id=digest,
            revision=current["revision"] + 1,
            created=now(),
            actor=actor,
        )
    )
    conn.execute(
        update(variants).where(variants.c.id == variant_id).values(artwork_id=digest)
    )
    # Existing compositions and allocations retain their immutable version IDs.
    return record(
        conn,
        actor,
        "variant.artwork.revised",
        variant_id,
        {
            "request": request_data,
            "artworkVersionId": identity,
            "revision": current["revision"] + 1,
            "previousArtworkVersionId": current["id"],
            "reason": payload.reason,
        },
        payload.key,
    )


def preview_import(conn, catalog_input, root):
    existing = {r["id"]: r for r in catalog(conn, True, root)}
    numbers = {r["orderNumber"].casefold(): r["id"] for r in existing.values()}
    seen_ids, seen_numbers, seen_variants = set(), set(), set()
    report = []
    for order in catalog_input.orders:
        status, reason = "new", "Ready to import"
        if order.id in seen_ids or order.orderNumber.casefold() in seen_numbers:
            status, reason = "conflict", "Duplicate ID or order number within the file"
        elif any(v.id in seen_variants for v in order.variants) or len(
            {v.id for v in order.variants}
        ) != len(order.variants):
            status, reason = "conflict", "Duplicate variant ID within the file"
        elif order.id in existing:
            original = existing[order.id]
            # Compare normalized business fields and exact images, ignoring legacy UI metadata.
            fields = ["name", "destination", "quantity", "side", "image"]
            old_variants = {
                v["id"]: {k: v[k] for k in fields} for v in original["variants"]
            }
            new_variants = {
                v.id: {k: getattr(v, k) for k in fields} for v in order.variants
            }
            equal = (
                all(
                    original[k] == getattr(order, k)
                    for k in ["orderNumber", "customer", "widthMm", "heightMm"]
                )
                and old_variants == new_variants
            )
            status, reason = (
                ("skip", "Identical order already imported")
                if equal
                else ("conflict", "ID exists with different contents")
            )
        elif order.orderNumber.casefold() in numbers:
            status, reason = "conflict", "Order number belongs to another ID"
        elif conn.execute(
            select(variants.c.id).where(
                variants.c.id.in_([v.id for v in order.variants])
            )
        ).first():
            status, reason = "conflict", "Variant ID already belongs to another order"
        seen_ids.add(order.id)
        seen_numbers.add(order.orderNumber.casefold())
        seen_variants.update(v.id for v in order.variants)
        report.append(
            {
                "id": order.id,
                "number": order.orderNumber,
                "status": status,
                "reason": reason,
            }
        )
    return report


def validate_sheet(conn, sheet, exclude_id=None):
    number_query = select(sheets.c.id).where(
        func.lower(sheets.c.number) == sheet.number.lower()
    )
    if exclude_id:
        number_query = number_query.where(sheets.c.id != exclude_id)
    fail(
        conn.execute(number_query).first(),
        "Sheet number already exists",
    )
    rectangles, resolved = [], []
    for p in sheet.placements:
        row = (
            conn.execute(
                select(variants.c.id, variants.c.side, orders.c.width, orders.c.height)
                .join(orders)
                .where(variants.c.id == p.variantId)
            )
            .mappings()
            .first()
        )
        fail(not row, "Unknown variant in composition", 422)
        fail(p.side != row["side"], "Placement side does not match artwork side", 422)
        version_query = select(artwork_versions).where(
            artwork_versions.c.variant_id == p.variantId
        )
        if p.artworkVersionId:
            version_query = version_query.where(
                artwork_versions.c.id == p.artworkVersionId
            )
        version = (
            conn.execute(
                version_query.order_by(artwork_versions.c.revision.desc()).limit(1)
            )
            .mappings()
            .first()
        )
        fail(not version, "Artwork revision does not belong to this variant", 422)
        resolved.append({**p.model_dump(), "artworkVersionId": version["id"]})
        w, h = (
            (row["height"], row["width"])
            if p.rotation in [90, 270]
            else (row["width"], row["height"])
        )
        fail(
            p.x + w > sheet.widthMm or p.y + h > sheet.heightMm,
            "Placement exceeds sheet bounds",
            422,
        )
        for x, y, width, height, side in rectangles:
            fail(
                side == p.side
                and p.x < x + width
                and p.x + w > x
                and p.y < y + height
                and p.y + h > y,
                "Placements overlap on the same sheet side",
                422,
            )
        rectangles.append((p.x, p.y, w, h, p.side))
    return resolved


def sheet_revision(conn, sheet_id):
    return conn.execute(
        select(func.count())
        .select_from(events)
        .where(
            events.c.entity_id == sheet_id,
            events.c.kind.in_(["sheet.created", "sheet.updated"]),
        )
    ).scalar_one()


def create_sheet(conn, sheet, actor):
    resolved = validate_sheet(conn, sheet)
    identity = uid()
    conn.execute(
        sheets.insert().values(
            id=identity,
            number=sheet.number,
            width=sheet.widthMm,
            height=sheet.heightMm,
            impressions=sheet.impressions,
            state="draft",
            placements=resolved,
            created=now(),
        )
    )
    record(conn, actor, "sheet.created", identity, {"number": sheet.number})
    return {"id": identity}


def update_sheet(conn, sheet_id, payload, actor):
    request_data = payload.model_dump(exclude={"key"})
    previous = existing_request(
        conn, payload.key, "sheet.updated", sheet_id, request_data
    )
    if previous:
        return previous
    current = (
        conn.execute(select(sheets).where(sheets.c.id == sheet_id)).mappings().first()
    )
    fail(not current, "Sheet not found", 404)
    fail(
        current["state"] != "draft",
        "Released sheets are immutable; create a reprint draft instead",
    )
    fail(
        sheet_revision(conn, sheet_id) != payload.expectedRevision,
        "Sheet draft changed; refresh and review before saving",
    )
    resolved = validate_sheet(conn, payload, sheet_id)
    conn.execute(
        update(sheets)
        .where(sheets.c.id == sheet_id)
        .values(
            number=payload.number,
            width=payload.widthMm,
            height=payload.heightMm,
            impressions=payload.impressions,
            placements=resolved,
        )
    )
    return record(
        conn,
        actor,
        "sheet.updated",
        sheet_id,
        {"request": request_data, "revision": payload.expectedRevision + 1},
        payload.key,
    )


def release(conn, sheet_id, actor, key, expected_revision=1):
    request_data = {"expectedRevision": expected_revision}
    previous = existing_request(conn, key, "sheet.released", sheet_id, request_data)
    if previous:
        return previous
    sheet = (
        conn.execute(select(sheets).where(sheets.c.id == sheet_id)).mappings().first()
    )
    fail(not sheet, "Sheet not found", 404)
    fail(sheet["state"] != "draft", "Only a draft sheet can be released")
    fail(
        sheet_revision(conn, sheet_id) != expected_revision,
        "Sheet draft changed; refresh and review before release",
    )
    counts = Counter(
        (p["variantId"], p["artworkVersionId"]) for p in sheet["placements"]
    )
    for (variant_id, version_id), count in counts.items():
        allocation_id = uid()
        conn.execute(
            allocations.insert().values(
                id=allocation_id,
                sheet_id=sheet_id,
                variant_id=variant_id,
                released=sheet["impressions"] * count,
                packed=0,
                cancelled=0,
                revision=1,
            )
        )
        conn.execute(
            allocation_artwork.insert().values(
                allocation_id=allocation_id, artwork_version_id=version_id
            )
        )
    conn.execute(update(sheets).where(sheets.c.id == sheet_id).values(state="released"))
    bump_pool(conn)
    return record(
        conn,
        actor,
        "sheet.released",
        sheet_id,
        {"request": request_data, "allocations": len(counts)},
        key,
    )


def allocation_rows(conn, active=False):
    query = (
        select(
            allocations,
            variants.c.name,
            variants.c.destination,
            artwork_versions.c.artwork_id,
            artwork_versions.c.id.label("artworkVersionId"),
            artwork_versions.c.revision.label("artworkRevision"),
            variants.c.side,
            orders.c.number.label("orderNumber"),
            orders.c.customer,
            orders.c.width.label("widthMm"),
            orders.c.height.label("heightMm"),
            sheets.c.number.label("sheetNumber"),
            artworks.c.state.label("readiness"),
        )
        .join(variants, allocations.c.variant_id == variants.c.id)
        .join(orders, variants.c.order_id == orders.c.id)
        .join(sheets, allocations.c.sheet_id == sheets.c.id)
        .join(
            allocation_artwork, allocation_artwork.c.allocation_id == allocations.c.id
        )
        .join(
            artwork_versions,
            allocation_artwork.c.artwork_version_id == artwork_versions.c.id,
        )
        .join(artworks, artwork_versions.c.artwork_id == artworks.c.id)
    )
    if active:
        query = query.where(
            allocations.c.released > allocations.c.packed + allocations.c.cancelled
        )
    return [
        {
            **r,
            "remaining": r["released"] - r["packed"] - r["cancelled"],
            "image": f"/api/artworks/{r['artwork_id']}",
        }
        for r in conn.execute(query).mappings()
    ]


def pack(conn, allocation_id, payload, actor):
    request_data = payload.model_dump(exclude={"key"})
    previous = existing_request(
        conn, payload.key, "allocation.packed", allocation_id, request_data
    )
    if previous:
        return previous
    if payload.scanId:
        scan = (
            conn.execute(select(scans).where(scans.c.id == payload.scanId))
            .mappings()
            .first()
        )
        fail(not scan, "Scan not found", 404)
        fail(
            scan["result"].get("poolRevision") != pool_revision(conn),
            "Active production changed since this scan; scan again",
        )
        candidate = next(
            (c for c in scan["result"]["candidates"] if c["id"] == allocation_id), None
        )
        fail(
            not candidate or candidate["revision"] != payload.revision,
            "Scan result is stale or does not contain this allocation",
        )
        reviews = (
            conn.execute(
                select(events)
                .where(
                    events.c.kind == "scan.reviewed",
                    events.c.entity_id == payload.scanId,
                )
                .order_by(events.c.created.desc())
            )
            .mappings()
            .all()
        )
        fail(
            not reviews
            or reviews[0]["payload"].get("allocationId") != allocation_id
            or reviews[0]["payload"].get("decision") != "confirm",
            "Confirm this allocation in candidate review before packing",
        )
    result = conn.execute(
        update(allocations)
        .where(
            allocations.c.id == allocation_id,
            allocations.c.revision == payload.revision,
            allocations.c.released - allocations.c.packed - allocations.c.cancelled
            >= payload.quantity,
        )
        .values(
            packed=allocations.c.packed + payload.quantity,
            revision=allocations.c.revision + 1,
        )
    )
    fail(
        result.rowcount != 1,
        "Allocation changed or quantity exceeds remaining work. Refresh before packing.",
    )
    bump_pool(conn)
    return record(
        conn,
        actor,
        "allocation.packed",
        allocation_id,
        {
            "request": request_data,
            "quantity": payload.quantity,
            "reason": payload.reason,
            "scanId": payload.scanId,
        },
        payload.key,
    )


def reverse_pack(conn, event_id, payload, actor):
    data = payload.model_dump(exclude={"key"})
    previous = existing_request(conn, payload.key, "packing.reversed", event_id, data)
    if previous:
        return previous
    original = (
        conn.execute(
            select(events).where(
                events.c.id == event_id, events.c.kind == "allocation.packed"
            )
        )
        .mappings()
        .first()
    )
    fail(not original, "Packing event not found", 404)
    # Event entity IDs are unique packing-event IDs here; serialization prevents double reversal.
    fail(
        conn.execute(
            select(events.c.id).where(
                events.c.kind == "packing.reversed", events.c.entity_id == event_id
            )
        ).first(),
        "Packing event is already reversed",
    )
    quantity = original["payload"]["quantity"]
    result = conn.execute(
        update(allocations)
        .where(
            allocations.c.id == original["entity_id"], allocations.c.packed >= quantity
        )
        .values(
            packed=allocations.c.packed - quantity, revision=allocations.c.revision + 1
        )
    )
    fail(result.rowcount != 1, "Cannot reverse this packing quantity")
    bump_pool(conn)
    return record(
        conn,
        actor,
        "packing.reversed",
        event_id,
        {
            "request": data,
            "allocationId": original["entity_id"],
            "quantity": quantity,
            "reason": payload.reason,
        },
        payload.key,
    )


def cancel(conn, allocation_id, payload, actor):
    data = payload.model_dump(exclude={"key"})
    previous = existing_request(
        conn, payload.key, "allocation.cancelled", allocation_id, data
    )
    if previous:
        return previous
    row = (
        conn.execute(select(allocations).where(allocations.c.id == allocation_id))
        .mappings()
        .first()
    )
    fail(not row, "Allocation not found", 404)
    remaining = row["released"] - row["packed"] - row["cancelled"]
    fail(remaining == 0, "No remaining work to cancel")
    conn.execute(
        update(allocations)
        .where(allocations.c.id == allocation_id)
        .values(cancelled=row["cancelled"] + remaining, revision=row["revision"] + 1)
    )
    bump_pool(conn)
    return record(
        conn,
        actor,
        "allocation.cancelled",
        allocation_id,
        {"request": data, "quantity": remaining, "reason": payload.reason},
        payload.key,
    )
