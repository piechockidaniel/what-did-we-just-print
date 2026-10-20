import hashlib
import hmac
import secrets
import time
from sqlalchemy import select, delete
from fastapi import HTTPException
from .db import users, sessions


def password_hash(password, salt=None):
    salt = salt or secrets.token_hex(16)
    digest = hashlib.scrypt(
        password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1
    ).hex()
    return f"{salt}:{digest}"


def authenticate(request, engine, development):
    if development:
        # Only the explicitly selected loopback development mode has an automatic identity.
        return {"name": "local-developer", "role": "admin", "development": True}
    token = request.cookies.get("print_session", "")
    with engine.connect() as conn:
        row = (
            conn.execute(
                select(users.c.name, users.c.role)
                .join(sessions, users.c.name == sessions.c.name)
                .where(
                    sessions.c.token_hash == hashlib.sha256(token.encode()).hexdigest(),
                    sessions.c.expires > time.time(),
                )
            )
            .mappings()
            .first()
        )
    if not row:
        raise HTTPException(401, "Sign in required")
    return {**row, "development": False}


def login(conn, name, password):
    user = conn.execute(select(users).where(users.c.name == name)).mappings().first()
    # Equal-cost hash for unknown users; never log supplied credentials.
    expected = user["password"] if user else password_hash("unavailable")
    if (
        not hmac.compare_digest(
            password_hash(password, expected.split(":")[0]), expected
        )
        or not user
    ):
        raise HTTPException(401, "Invalid credentials")
    token = secrets.token_urlsafe(32)
    conn.execute(delete(sessions).where(sessions.c.expires < time.time()))
    conn.execute(
        sessions.insert().values(
            token_hash=hashlib.sha256(token.encode()).hexdigest(),
            name=name,
            expires=time.time() + 28800,
        )
    )
    return token
