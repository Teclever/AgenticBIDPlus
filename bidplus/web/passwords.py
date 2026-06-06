"""Password hashing (bcrypt) + the Teclever-domain email guard.

Uses the `bcrypt` library directly (passlib 1.7.4 is incompatible with bcrypt 4.x — its
backend probe raises on `bcrypt.__about__`). Import-light (no FastAPI) so the `bidplus.users`
CLI and the auth layer share one implementation. Email must be on the `teclever` domain
(WEBAPP_DESIGN §16.3). bcrypt hashes only the first 72 bytes — we truncate explicitly so a
long password never raises.
"""

from __future__ import annotations

import re

import bcrypt

# user@teclever.<tld> (teclever.com, teclever.in, …), case-insensitive.
_TECLEVER_EMAIL = re.compile(r"^[^@\s]+@teclever\.[a-z.]+$", re.IGNORECASE)


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8")[:72], bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8")[:72], password_hash.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def is_teclever_email(email: str) -> bool:
    return bool(_TECLEVER_EMAIL.match((email or "").strip()))
