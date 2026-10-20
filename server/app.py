import hashlib
import os
from pathlib import Path
import time
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy import select, update, delete, text
from sqlalchemy.exc import IntegrityError
from starlette.middleware.trustedhost import TrustedHostMiddleware
from fastapi.staticfiles import StaticFiles
from .db import (
    make_engine,
    ROOT,
    artworks,
    sheets,
    allocations,
    events,
    scans,
    jobs,
    sessions,
    stations,
    artwork_versions,
)
from . import schemas, domain, auth
from .storage import decode_image


def create_app(database_url=None, data_dir=None, development=None):
    app = FastAPI(title="What Did We Just Print?", version="0.2.0")
    engine = make_engine(database_url)
    root = Path(data_dir or os.getenv("PRINT_DATA_DIR", ROOT / "data"))
    root.mkdir(parents=True, exist_ok=True)
    development = (
        (os.getenv("PRINT_DEV", "0") == "1") if development is None else development
    )
    app.state.engine, app.state.data_dir = engine, root
    with engine.begin() as conn:
        from .db import schema_versions

        conn.execute(update(schema_versions).values(version=schema_versions.c.version))
        if not conn.execute(
            select(sheets.c.id).where(sheets.c.id == "__workflow_lock__")
        ).first():
            conn.execute(
                sheets.insert().values(
                    id="__workflow_lock__",
                    number="__workflow_lock__",
                    width=1,
                    height=1,
                    impressions=1,
                    state="internal",
                    placements=[],
                    created=domain.now(),
                )
            )

    allowed = os.getenv("PRINT_ALLOWED_HOSTS", "127.0.0.1,localhost,testserver").split(
        ","
    )
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=allowed)

    @app.middleware("http")
    async def guard(request: Request, call_next):
        if not request.url.path.startswith("/api/"):
            return await call_next(request)
        # Bound uploads before JSON parsing, including chunked requests.
        limit = 80 * 1024 * 1024
        chunks, size = [], 0
        async for chunk in request.stream():
            size += len(chunk)
            if size > limit:
                return JSONResponse(
                    {
                        "detail": "Request exceeds 80 MB; split the catalog into smaller files"
                    },
                    413,
                )
            chunks.append(chunk)
        request._body = b"".join(chunks)
        if request.method not in ["GET", "HEAD", "OPTIONS"]:
            origin = request.headers.get("origin")
            approved = os.getenv(
                "PRINT_ORIGIN",
                "http://127.0.0.1:5173,http://127.0.0.1:4173"
                if development
                else "http://127.0.0.1:5173",
            ).split(",")
            if origin and origin not in approved:
                return JSONResponse({"detail": "Origin is not allowed"}, 403)
            if request.headers.get("x-print-client") != "web":
                return JSONResponse(
                    {"detail": "Missing request protection header"}, 403
                )
        if request.url.path not in ["/api/health", "/api/login"]:
            try:
                request.state.user = auth.authenticate(request, engine, development)
            except HTTPException as exc:
                return JSONResponse({"detail": exc.detail}, exc.status_code)
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    @app.exception_handler(IntegrityError)
    async def conflict(_, __):
        return JSONResponse(
            {"detail": "Conflicting record; refresh and try again"}, 409
        )

    def actor(request, supervisor=False):
        user = request.state.user
        if supervisor and user["role"] not in ["supervisor", "admin"]:
            raise HTTPException(403, "Supervisor access required")
        return user["name"]

    def lock(conn):
        conn.execute(
            update(sheets)
            .where(sheets.c.id == "__workflow_lock__")
            .values(impressions=sheets.c.impressions + 1)
        )

    @app.get("/api/health")
    def health():
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return {
            "status": "ok",
            "database": engine.dialect.name,
            "development": development,
        }

    @app.get("/api/session")
    def session(request: Request):
        return request.state.user

    @app.post("/api/login")
    def login(payload: schemas.Login):
        with engine.begin() as conn:
            token = auth.login(conn, payload.name, payload.password)
        response = JSONResponse({"status": "signed-in"})
        response.set_cookie(
            "print_session",
            token,
            max_age=28800,
            httponly=True,
            samesite="strict",
            secure=not development,
        )
        return response

    @app.post("/api/logout")
    def logout(request: Request):
        with engine.begin() as conn:
            conn.execute(
                delete(sessions).where(
                    sessions.c.token_hash
                    == hashlib.sha256(
                        request.cookies.get("print_session", "").encode()
                    ).hexdigest()
                )
            )
        response = JSONResponse({"status": "signed-out"})
        response.delete_cookie("print_session")
        return response

    @app.get("/api/orders")
    def get_orders():
        with engine.connect() as conn:
            return domain.catalog(conn)

    @app.post("/api/orders", status_code=201)
    def add_order(payload: schemas.Order, request: Request):
        with engine.begin() as conn:
            lock(conn)
            return domain.create_order(conn, payload, root, actor(request))

    @app.get("/api/artworks/{identity}")
    # Originals remain readable for archived revisions and live allocation snapshots.
    def artwork(identity: str):
        with engine.connect() as conn:
            row = (
                conn.execute(select(artworks).where(artworks.c.id == identity))
                .mappings()
                .first()
            )
        domain.fail(not row, "Artwork not found", 404)
        return FileResponse(root / "artwork" / row["id"], media_type=row["mime"])

    @app.get("/api/variants/{identity}/artwork")
    def get_artwork_versions(identity: str):
        with engine.connect() as conn:
            return domain.list_artwork_versions(conn, identity)

    @app.post("/api/variants/{identity}/artwork")
    def revise_artwork(identity: str, payload: schemas.ArtworkUpdate, request: Request):
        with engine.begin() as conn:
            return domain.revise_artwork(
                conn, identity, payload, root, actor(request, True)
            )

    @app.get("/api/catalog/export")
    def export():
        with engine.connect() as conn:
            # Export retains the original schema; UI-only artwork IDs are omitted.
            data = domain.catalog(conn, True, root)
            for order in data:
                for variant in order["variants"]:
                    variant.pop("artworkId", None)
                    variant.pop("artworkVersionId", None)
                    variant.pop("artworkRevision", None)
        return {
            "schemaVersion": 1,
            "exportedAt": domain.now(),
            "imageEncoding": "data-url",
            "orders": data,
        }

    @app.post("/api/catalog/preview")
    def preview(payload: schemas.Catalog):
        for order in payload.orders:
            for variant in order.variants:
                decode_image(variant.image)
        with engine.connect() as conn:
            return domain.preview_import(conn, payload, root)

    @app.post("/api/catalog/import")
    def import_catalog(payload: schemas.Catalog, request: Request):
        with engine.begin() as conn:
            lock(conn)
            preview = domain.preview_import(conn, payload, root)
            domain.fail(
                any(r["status"] == "conflict" for r in preview),
                "Import contains conflicts; nothing was changed",
            )
            for order, item in zip(payload.orders, preview):
                if item["status"] == "new":
                    domain.create_order(conn, order, root, actor(request))
            return {
                "imported": sum(r["status"] == "new" for r in preview),
                "skipped": sum(r["status"] == "skip" for r in preview),
            }

    @app.get("/api/sheets")
    def get_sheets():
        with engine.connect() as conn:
            rows = (
                conn.execute(
                    select(sheets)
                    .where(sheets.c.state != "internal")
                    .order_by(sheets.c.created.desc())
                )
                .mappings()
                .all()
            )
            ids = {p["artworkVersionId"] for row in rows for p in row["placements"]}
            images = {
                row["id"]: f"/api/artworks/{row['artwork_id']}"
                for row in conn.execute(
                    select(artwork_versions.c.id, artwork_versions.c.artwork_id).where(
                        artwork_versions.c.id.in_(ids)
                    )
                ).mappings()
            }
            return [
                {
                    **r,
                    "revision": domain.sheet_revision(conn, r["id"]),
                    "artworkImages": {
                        p["artworkVersionId"]: images[p["artworkVersionId"]]
                        for p in r["placements"]
                    },
                }
                for r in rows
            ]

    @app.post("/api/sheets", status_code=201)
    def add_sheet(payload: schemas.Sheet, request: Request):
        with engine.begin() as conn:
            lock(conn)
            return domain.create_sheet(conn, payload, actor(request))

    @app.put("/api/sheets/{identity}")
    def edit_sheet(identity: str, payload: schemas.SheetUpdate, request: Request):
        with engine.begin() as conn:
            return domain.update_sheet(conn, identity, payload, actor(request))

    @app.post("/api/sheets/{identity}/release")
    def release(identity: str, payload: schemas.Release, request: Request):
        with engine.begin() as conn:
            return domain.release(
                conn, identity, actor(request), payload.key, payload.expectedRevision
            )

    @app.get("/api/allocations")
    def get_allocations(active: bool = False):
        with engine.connect() as conn:
            return domain.allocation_rows(conn, active)

    @app.post("/api/allocations/{identity}/pack")
    def pack(identity: str, payload: schemas.Packing, request: Request):
        with engine.begin() as conn:
            return domain.pack(conn, identity, payload, actor(request))

    @app.post("/api/allocations/{identity}/cancel")
    def cancel(identity: str, payload: schemas.Reason, request: Request):
        with engine.begin() as conn:
            return domain.cancel(conn, identity, payload, actor(request, True))

    @app.post("/api/packing/{identity}/reverse")
    def reverse(identity: str, payload: schemas.Reason, request: Request):
        with engine.begin() as conn:
            return domain.reverse_pack(conn, identity, payload, actor(request, True))

    @app.get("/api/history")
    def history(limit: int = 100, offset: int = 0):
        domain.fail(not 1 <= limit <= 500 or offset < 0, "Invalid pagination", 422)
        with engine.connect() as conn:
            return [
                dict(r)
                for r in conn.execute(
                    select(events)
                    .order_by(events.c.created.desc())
                    .limit(limit)
                    .offset(offset)
                ).mappings()
            ]

    @app.get("/api/jobs")
    def get_jobs():
        with engine.connect() as conn:
            return [dict(r) for r in conn.execute(select(jobs)).mappings()]

    @app.get("/api/stations")
    def get_stations():
        with engine.connect() as conn:
            return [
                dict(r)
                for r in conn.execute(
                    select(stations).order_by(stations.c.name)
                ).mappings()
            ]

    @app.post("/api/stations", status_code=201)
    def add_station(payload: schemas.Station, request: Request):
        name = actor(request, True)
        identity = domain.uid()
        with engine.begin() as conn:
            lock(conn)
            conn.execute(
                stations.insert().values(
                    id=identity,
                    name=payload.name,
                    max_width=payload.maxWidthMm,
                    max_height=payload.maxHeightMm,
                    notes=payload.notes,
                )
            )
            domain.record(conn, name, "station.created", identity, payload.model_dump())
        return {"id": identity}

    @app.post("/api/jobs/{identity}/retry")
    def retry(identity: str, payload: schemas.Reason, request: Request):
        with engine.begin() as conn:
            lock(conn)
            job = (
                conn.execute(select(jobs).where(jobs.c.id == identity))
                .mappings()
                .first()
            )
            domain.fail(
                not job or job["state"] != "failed", "Only failed jobs can be retried"
            )
            conn.execute(
                update(jobs)
                .where(jobs.c.id == identity)
                .values(state="pending", attempts=0, lease_until=0, error=None)
            )
            conn.execute(
                update(artworks)
                .where(artworks.c.id == job["artwork_id"])
                .values(state="pending", error=None)
            )
            domain.record(
                conn,
                actor(request, True),
                "job.retried",
                identity,
                {"reason": payload.reason},
            )
        return {"status": "pending"}

    @app.post("/api/scans")
    def scan(payload: schemas.Scan, request: Request):
        from vision.matching import match

        started = time.perf_counter()
        # Serialize the brief pool snapshot; release the guard before CPU work.
        with engine.begin() as conn:
            lock(conn)
            rows = domain.allocation_rows(conn, True)
            pool_revision = domain.pool_revision(conn)
            station = (
                conn.execute(select(stations).where(stations.c.id == payload.stationId))
                .mappings()
                .first()
                if payload.stationId
                else None
            )
            domain.fail(payload.stationId and not station, "Station not found", 404)
        if payload.sheetId:
            rows = [r for r in rows if r["sheet_id"] == payload.sheetId]
        if station:
            rows = [
                r
                for r in rows
                if (
                    r["widthMm"] <= station["max_width"]
                    and r["heightMm"] <= station["max_height"]
                )
                or (
                    r["heightMm"] <= station["max_width"]
                    and r["widthMm"] <= station["max_height"]
                )
            ]
        result = match(root, payload.image, rows, payload.corners, payload.autoCrop)
        result["poolRevision"] = pool_revision
        result["sheetFilter"] = payload.sheetId
        result["stationId"] = payload.stationId
        result["stationSizing"] = (
            "Configured product class only; physical calibration not established"
        )
        result["durationMs"] = round((time.perf_counter() - started) * 1000)
        identity = domain.uid()
        raw, _, _ = decode_image(payload.image)
        captures = root / "captures"
        captures.mkdir(exist_ok=True)
        (captures / identity).write_bytes(raw)
        with engine.begin() as conn:
            conn.execute(
                scans.insert().values(
                    id=identity,
                    created=domain.now(),
                    actor=actor(request),
                    result=result,
                )
            )
            domain.record(
                conn,
                actor(request),
                "scan.created",
                identity,
                {"decision": result["decision"], "algorithm": result["algorithm"]},
            )
        return {"id": identity, **result}

    @app.post("/api/scans/{identity}/review")
    def review(identity: str, payload: schemas.Review, request: Request):
        with engine.begin() as conn:
            lock(conn)
            scan = (
                conn.execute(select(scans).where(scans.c.id == identity))
                .mappings()
                .first()
            )
            domain.fail(not scan, "Scan not found", 404)
            domain.fail(
                scan["result"].get("poolRevision") != domain.pool_revision(conn),
                "Active production changed; scan again",
            )
            if payload.decision == "confirm":
                candidate = next(
                    (
                        c
                        for c in scan["result"]["candidates"]
                        if c["id"] == payload.allocationId
                    ),
                    None,
                )
                domain.fail(not candidate, "Allocation is not a candidate in this scan")
                current = (
                    conn.execute(
                        select(allocations).where(
                            allocations.c.id == payload.allocationId
                        )
                    )
                    .mappings()
                    .first()
                )
                domain.fail(
                    not current
                    or current["revision"] != candidate["revision"]
                    or current["released"] <= current["packed"] + current["cancelled"],
                    "Candidate is stale; scan again",
                )
            return domain.record(
                conn, actor(request), "scan.reviewed", identity, payload.model_dump()
            )

    if (ROOT / "dist").is_dir():
        app.mount("/", StaticFiles(directory=ROOT / "dist", html=True), name="frontend")
    return app


app = create_app()
