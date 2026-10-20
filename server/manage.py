"""Local administration. Passwords are entered privately, never as CLI arguments."""

import argparse
import getpass
from pathlib import Path
from sqlalchemy import select
from .db import make_engine, users, ROOT
from .auth import password_hash


def main():
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    user = commands.add_parser("create-user")
    user.add_argument("name")
    user.add_argument(
        "--role", choices=["operator", "supervisor", "admin"], default="operator"
    )
    backup = commands.add_parser("backup")
    backup.add_argument("destination", type=Path)
    check = commands.add_parser("verify-backup")
    check.add_argument("source", type=Path)
    restore = commands.add_parser("restore")
    restore.add_argument("source", type=Path)
    restore.add_argument("destination", type=Path)
    migrate = commands.add_parser("migrate")
    migrate.add_argument("--target", type=int, default=2, choices=[1, 2])
    migrate.add_argument("--downgrade", action="store_true")
    commands.add_parser("schema-version")
    args = parser.parse_args()
    if args.command in ["migrate", "schema-version"]:
        from .migrations import current, upgrade, downgrade

        engine = make_engine(initialize=False)
        if args.command == "schema-version":
            with engine.connect() as conn:
                print(f"Database schema version: {current(conn)}")
        else:
            version = (
                downgrade(engine, args.target)
                if args.downgrade
                else upgrade(engine, args.target)
            )
            print(f"Database schema version: {version}")
        engine.dispose()
        return
    if args.command == "create-user":
        password = getpass.getpass("Password (at least 12 characters): ")
        if len(password) < 12 or password != getpass.getpass("Confirm password: "):
            raise SystemExit("Passwords must match and have at least 12 characters")
        with make_engine().begin() as conn:
            if conn.execute(
                select(users.c.name).where(users.c.name == args.name)
            ).first():
                raise SystemExit("User already exists")
            conn.execute(
                users.insert().values(
                    name=args.name, role=args.role, password=password_hash(password)
                )
            )
        print("User created")
    elif args.command == "backup":
        import os

        root = Path(os.getenv("PRINT_DATA_DIR", ROOT / "data"))
        if os.getenv("DATABASE_URL", "").startswith("postgres"):
            raise SystemExit(
                "PostgreSQL: use pg_dump plus a consistent private-storage snapshot; see runbook"
            )
        from .backup import snapshot

        snapshot(root, args.destination)
        print(
            "Checksummed backup written; perform a restore drill before relying on it"
        )
    elif args.command == "verify-backup":
        from .backup import verify

        manifest = verify(args.source)
        print(f"Verified {len(manifest['files'])} snapshot files")
    elif args.command == "restore":
        from .backup import restore

        count = restore(args.source, args.destination)
        print(
            f"Restored {count} files to a new directory. Set PRINT_DATA_DIR and validate before cutover."
        )


if __name__ == "__main__":
    main()
