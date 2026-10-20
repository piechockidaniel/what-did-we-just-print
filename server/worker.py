"""Durable feature preparation worker. Run as a separate process."""

import time
import argparse
from sqlalchemy import select, update, or_
from .db import make_engine, jobs, artworks, ROOT, sheets
from .domain import bump_pool
from vision.matching import prepare, cache_path


def reconcile_cache(engine, root):
    with engine.begin() as conn:
        conn.execute(
            update(sheets)
            .where(sheets.c.id == "__workflow_lock__")
            .values(impressions=sheets.c.impressions + 1)
        )
        ready = (
            conn.execute(select(artworks.c.id).where(artworks.c.state == "ready"))
            .scalars()
            .all()
        )
        for identity in ready:
            if not cache_path(root, identity).exists():
                conn.execute(
                    update(artworks)
                    .where(artworks.c.id == identity)
                    .values(state="pending", error=None)
                )
                bump_pool(conn)
                conn.execute(
                    update(jobs)
                    .where(jobs.c.artwork_id == identity)
                    .values(state="pending", attempts=0, lease_until=0, error=None)
                )


def run_one(engine, root):
    timestamp = time.time()
    with engine.begin() as conn:
        job = (
            conn.execute(
                select(jobs)
                .where(
                    or_(
                        jobs.c.state == "pending",
                        (jobs.c.state == "running") & (jobs.c.lease_until < timestamp),
                    ),
                    jobs.c.attempts < 3,
                )
                .order_by(jobs.c.id)
                .limit(1)
            )
            .mappings()
            .first()
        )
        if not job:
            # Expired third-attempt jobs must not remain in running forever.
            exhausted = (
                conn.execute(
                    select(jobs).where(
                        jobs.c.state == "running",
                        jobs.c.lease_until < timestamp,
                        jobs.c.attempts >= 3,
                    )
                )
                .mappings()
                .all()
            )
            for row in exhausted:
                conn.execute(
                    update(jobs)
                    .where(jobs.c.id == row["id"])
                    .values(state="failed", error="Worker lease exhausted")
                )
                conn.execute(
                    update(artworks)
                    .where(artworks.c.id == row["artwork_id"])
                    .values(state="failed", error="Worker lease exhausted")
                )
            return False
        claimed = conn.execute(
            update(jobs)
            .where(
                jobs.c.id == job["id"],
                jobs.c.state == job["state"],
                jobs.c.lease_until == job["lease_until"],
            )
            .values(
                state="running",
                lease_until=timestamp + 300,
                attempts=jobs.c.attempts + 1,
            )
        )
        if claimed.rowcount != 1:
            return True
        artwork = (
            conn.execute(select(artworks).where(artworks.c.id == job["artwork_id"]))
            .mappings()
            .one()
        )
    error = None
    try:
        prepare(root, artwork["id"], root / "artwork" / artwork["id"])
    except Exception as exc:
        error = str(exc)[:500]
    with engine.begin() as conn:
        conn.execute(
            update(sheets)
            .where(sheets.c.id == "__workflow_lock__")
            .values(impressions=sheets.c.impressions + 1)
        )
        # Fence completion against a replacement worker after an expired lease.
        owned = conn.execute(
            update(jobs)
            .where(
                jobs.c.id == job["id"],
                jobs.c.lease_until == timestamp + 300,
                jobs.c.state == "running",
            )
            .values(state="failed" if error else "ready", error=error)
        )
        if owned.rowcount:
            conn.execute(
                update(artworks)
                .where(artworks.c.id == artwork["id"])
                .values(state="failed" if error else "ready", error=error)
            )
            bump_pool(conn)
    return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    import os
    from pathlib import Path

    engine = make_engine()
    root = Path(os.getenv("PRINT_DATA_DIR", ROOT / "data"))
    reconcile_cache(engine, root)
    while True:
        worked = run_one(engine, root)
        if args.once:
            return
        if not worked:
            time.sleep(1)


if __name__ == "__main__":
    main()
