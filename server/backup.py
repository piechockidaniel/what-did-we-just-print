"""Checksummed SQLite snapshots. PostgreSQL uses pg_dump plus private storage."""

from pathlib import Path

import hashlib
import json
import shutil
import sqlite3


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def verify(directory):
    directory = directory.resolve()
    manifest = json.loads((directory / "snapshot.json").read_text(encoding="utf-8"))
    if manifest.get("schema") != 1:
        raise ValueError("Unsupported snapshot schema")
    for relative, expected in manifest["files"].items():
        relative_path = Path(relative)
        if (
            relative_path.is_absolute()
            or relative_path.drive
            or ".." in relative_path.parts
        ):
            raise ValueError("Snapshot contains an unsafe file path")
        path = (directory / relative).resolve()
        if (
            not path.is_relative_to(directory)
            or not path.is_file()
            or digest(path) != expected
        ):
            raise ValueError("Snapshot missing, altered or unsafe file")
    if "production.db" not in manifest["files"]:
        raise ValueError("Snapshot must include the production database")
    with sqlite3.connect(directory / "production.db") as conn:
        if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError("Database integrity check failed")
        for (identity,) in conn.execute("SELECT id FROM artworks"):
            if f"artwork/{identity}" not in manifest["files"]:
                raise ValueError("Database references artwork absent from the snapshot")
    return manifest


def snapshot(source, destination):
    source, destination = source.resolve(), destination.resolve()
    if destination.exists() or destination.is_relative_to(source):
        raise ValueError("Use a new destination outside the data directory")
    if not (source / "production.db").is_file():
        raise ValueError("SQLite production.db not found")
    destination.mkdir(parents=True)
    with (
        sqlite3.connect(source / "production.db") as current,
        sqlite3.connect(destination / "production.db") as backup,
    ):
        current.backup(backup)
    for name in ["artwork", "features", "captures"]:
        if (source / name).exists():
            shutil.copytree(source / name, destination / name)
    manifest = {
        "schema": 1,
        "files": {
            path.relative_to(destination).as_posix(): digest(path)
            for path in destination.rglob("*")
            if path.is_file()
        },
    }
    (destination / "snapshot.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    return verify(destination)


def restore(source, destination):
    manifest = verify(source)
    source, destination = source.resolve(), destination.resolve()
    if destination.exists() or destination.is_relative_to(source):
        raise ValueError("Restore requires a new directory outside the snapshot")
    destination.mkdir(parents=True)
    for relative in manifest["files"]:
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source / relative, target)
    return len(manifest["files"])
