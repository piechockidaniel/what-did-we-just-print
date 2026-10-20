"""Database schema and transactions. SQLite is a local-development fallback."""

import os
from pathlib import Path
from sqlalchemy import (
    create_engine,
    MetaData,
    Table,
    Column,
    String,
    Integer,
    Float,
    JSON,
    ForeignKey,
    CheckConstraint,
    event,
    UniqueConstraint,
)

ROOT = Path(__file__).resolve().parents[1]
metadata = MetaData()
schema_versions = Table(
    "schema_versions", metadata, Column("version", Integer, primary_key=True)
)
pool_state = Table(
    "pool_state",
    metadata,
    Column("id", String, primary_key=True),
    Column("revision", Integer, nullable=False),
)

orders = Table(
    "orders",
    metadata,
    Column("id", String, primary_key=True),
    Column("number", String, unique=True, nullable=False),
    Column("customer", String, nullable=False),
    Column("width", Float, nullable=False),
    Column("height", Float, nullable=False),
    Column("created", String, nullable=False),
)
artworks = Table(
    "artworks",
    metadata,
    Column("id", String, primary_key=True),
    Column("path", String, nullable=False),
    Column("mime", String, nullable=False),
    Column("width", Integer),
    Column("height", Integer),
    Column("state", String, nullable=False, default="pending"),
    Column("error", String),
)
variants = Table(
    "variants",
    metadata,
    Column("id", String, primary_key=True),
    Column("order_id", ForeignKey("orders.id"), nullable=False),
    Column("artwork_id", ForeignKey("artworks.id"), nullable=False),
    Column("name", String, nullable=False),
    Column("destination", String, nullable=False),
    Column("quantity", Integer, nullable=False),
    Column("side", String, nullable=False),
    CheckConstraint("quantity > 0"),
)
artwork_versions = Table(
    "artwork_versions",
    metadata,
    Column("id", String, primary_key=True),
    Column("variant_id", ForeignKey("variants.id"), nullable=False),
    Column("artwork_id", ForeignKey("artworks.id"), nullable=False),
    Column("revision", Integer, nullable=False),
    Column("created", String, nullable=False),
    Column("actor", String, nullable=False),
    UniqueConstraint("variant_id", "revision", name="uq_variant_artwork_revision"),
    CheckConstraint("revision > 0"),
)
sheets = Table(
    "sheets",
    metadata,
    Column("id", String, primary_key=True),
    Column("number", String, unique=True, nullable=False),
    Column("width", Float, nullable=False),
    Column("height", Float, nullable=False),
    Column("impressions", Integer, nullable=False),
    Column("state", String, nullable=False),
    Column("placements", JSON, nullable=False),
    Column("created", String, nullable=False),
)
allocations = Table(
    "allocations",
    metadata,
    Column("id", String, primary_key=True),
    Column("sheet_id", ForeignKey("sheets.id"), nullable=False),
    Column("variant_id", ForeignKey("variants.id"), nullable=False),
    Column("released", Integer, nullable=False),
    Column("packed", Integer, nullable=False, default=0),
    Column("cancelled", Integer, nullable=False, default=0),
    Column("revision", Integer, nullable=False, default=1),
    CheckConstraint(
        "released > 0 AND packed >= 0 AND cancelled >= 0 AND packed + cancelled <= released"
    ),
)
allocation_artwork = Table(
    "allocation_artwork",
    metadata,
    Column("allocation_id", ForeignKey("allocations.id"), primary_key=True),
    Column("artwork_version_id", ForeignKey("artwork_versions.id"), nullable=False),
)
events = Table(
    "events",
    metadata,
    Column("id", String, primary_key=True),
    Column("kind", String, nullable=False),
    Column("entity_id", String, nullable=False),
    Column("actor", String, nullable=False),
    Column("created", String, nullable=False),
    Column("payload", JSON, nullable=False),
    Column("request_key", String, unique=True),
)
scans = Table(
    "scans",
    metadata,
    Column("id", String, primary_key=True),
    Column("created", String, nullable=False),
    Column("actor", String, nullable=False),
    Column("result", JSON, nullable=False),
)
jobs = Table(
    "jobs",
    metadata,
    Column("id", String, primary_key=True),
    Column("artwork_id", ForeignKey("artworks.id"), unique=True),
    Column("state", String, nullable=False),
    Column("lease_until", Float, nullable=False, default=0),
    Column("attempts", Integer, nullable=False, default=0),
    Column("error", String),
)
users = Table(
    "users",
    metadata,
    Column("name", String, primary_key=True),
    Column("password", String, nullable=False),
    Column("role", String, nullable=False),
)
sessions = Table(
    "sessions",
    metadata,
    Column("token_hash", String, primary_key=True),
    Column("name", ForeignKey("users.name"), nullable=False),
    Column("expires", Float, nullable=False),
)
stations = Table(
    "stations",
    metadata,
    Column("id", String, primary_key=True),
    Column("name", String, unique=True, nullable=False),
    Column("max_width", Float, nullable=False),
    Column("max_height", Float, nullable=False),
    Column("notes", String, nullable=False),
)


def make_engine(url=None, initialize=True):
    directory = Path(os.getenv("PRINT_DATA_DIR", ROOT / "data"))
    directory.mkdir(parents=True, exist_ok=True)
    url = url or os.getenv("DATABASE_URL", f"sqlite:///{directory / 'production.db'}")
    engine = create_engine(
        url,
        connect_args={"timeout": 30, "check_same_thread": False}
        if url.startswith("sqlite:")
        else {"connect_timeout": 5},
        hide_parameters=True,
    )
    if engine.dialect.name == "sqlite":

        @event.listens_for(engine, "connect")
        def configure(connection, _):
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("PRAGMA journal_mode=WAL")

    if initialize:
        from .migrations import upgrade

        upgrade(engine)
    return engine
