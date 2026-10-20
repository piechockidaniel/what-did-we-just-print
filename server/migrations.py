"""Versioned, transactional schema upgrades. Stop writers and back up first.

The v1→v2 migration pins pre-existing allocations and compositions to artwork
revision 1. A downgrade is refused once revisions exist: old code would otherwise
misidentify historical allocations through the latest artwork pointer.
"""

from datetime import datetime, timezone
from uuid import uuid4, uuid5, NAMESPACE_URL
from sqlalchemy import inspect, select, update, func
from .db import (
    metadata,
    schema_versions,
    pool_state,
    variants,
    orders,
    allocations,
    sheets,
    events,
    artwork_versions,
    allocation_artwork,
)

LATEST = 2


def lock_schema(conn):
    if conn.dialect.name == "postgresql":
        conn.exec_driver_sql("SELECT pg_advisory_xact_lock(726782)")
    elif conn.dialect.name == "sqlite":
        conn.exec_driver_sql("BEGIN IMMEDIATE")
    else:
        raise RuntimeError("Only PostgreSQL and SQLite migrations are supported")


def current(conn):
    if not inspect(conn).has_table("schema_versions"):
        return None
    return conn.execute(select(schema_versions.c.version)).scalar_one()


def migration_event(conn, before, after):
    conn.execute(
        events.insert().values(
            id=str(uuid4()),
            kind="schema.migrated",
            entity_id="database",
            actor="migration-cli",
            created=datetime.now(timezone.utc).isoformat(),
            payload={"from": before, "to": after},
            request_key=None,
        )
    )


def upgrade(engine, target=LATEST):
    if target not in [1, 2]:
        raise ValueError("Unsupported migration target")
    with engine.begin() as conn:
        lock_schema(conn)
        version = current(conn)
        if version is None:
            tables = list(metadata.sorted_tables)
            if target == 1:
                tables = [
                    t for t in tables if t not in [artwork_versions, allocation_artwork]
                ]
            metadata.create_all(conn, tables=tables)
            conn.execute(schema_versions.insert().values(version=target))
        elif version not in [1, 2] or version > target:
            raise RuntimeError(
                "Unsupported schema version; use an explicit compatible migration or restore"
            )
        elif version == 1 and target == 2:
            # Coordinate with the v1 workflow-write guard while seeding references.
            conn.execute(
                update(sheets)
                .where(sheets.c.id == "__workflow_lock__")
                .values(impressions=sheets.c.impressions + 1)
            )
            artwork_versions.create(conn, checkfirst=True)
            allocation_artwork.create(conn, checkfirst=True)
            versions = {}
            for row in conn.execute(
                select(variants, orders.c.created).join(orders)
            ).mappings():
                identity = str(
                    uuid5(NAMESPACE_URL, "wdwjp/artwork-version/1/" + row["id"])
                )
                conn.execute(
                    artwork_versions.insert().values(
                        id=identity,
                        variant_id=row["id"],
                        artwork_id=row["artwork_id"],
                        revision=1,
                        created=row["created"],
                        actor="migration:v2",
                    )
                )
                versions[row["id"]] = identity
            for row in conn.execute(select(allocations)).mappings():
                conn.execute(
                    allocation_artwork.insert().values(
                        allocation_id=row["id"],
                        artwork_version_id=versions[row["variant_id"]],
                    )
                )
            for row in conn.execute(
                select(sheets).where(sheets.c.state != "internal")
            ).mappings():
                composition = [
                    {**p, "artworkVersionId": versions[p["variantId"]]}
                    for p in row["placements"]
                ]
                conn.execute(
                    update(sheets)
                    .where(sheets.c.id == row["id"])
                    .values(placements=composition)
                )
            conn.execute(update(pool_state).values(revision=pool_state.c.revision + 1))
            conn.execute(update(schema_versions).values(version=2))
            migration_event(conn, 1, 2)
        if not conn.execute(select(pool_state.c.id)).first():
            conn.execute(pool_state.insert().values(id="active", revision=1))
    return target


def downgrade(engine, target=1):
    if target != 1:
        raise ValueError("Only the v2→v1 downgrade is supported")
    with engine.begin() as conn:
        lock_schema(conn)
        if current(conn) != 2:
            raise RuntimeError("Downgrade requires schema v2")
        if conn.execute(
            select(func.count())
            .select_from(artwork_versions)
            .where(artwork_versions.c.revision > 1)
        ).scalar_one():
            raise RuntimeError(
                "Artwork revisions exist. Restore a matching backup instead of losing historical bindings."
            )
        conn.execute(
            update(sheets)
            .where(sheets.c.id == "__workflow_lock__")
            .values(impressions=sheets.c.impressions + 1)
        )
        for row in conn.execute(
            select(sheets).where(sheets.c.state != "internal")
        ).mappings():
            placements = [
                {k: v for k, v in p.items() if k != "artworkVersionId"}
                for p in row["placements"]
            ]
            conn.execute(
                update(sheets)
                .where(sheets.c.id == row["id"])
                .values(placements=placements)
            )
        allocation_artwork.drop(conn)
        artwork_versions.drop(conn)
        conn.execute(update(schema_versions).values(version=1))
        migration_event(conn, 2, 1)
    return 1
