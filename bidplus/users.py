"""User management CLI (WEBAPP_DESIGN §16.3) — run MANUALLY on the deploy box.

    python -m bidplus.users add    <email> [--password PW]
    python -m bidplus.users edit   <email> [--password PW]      # change password
    python -m bidplus.users remove <email>
    python -m bidplus.users list

No self-signup, no web admin. Passwords are bcrypt-hashed; the email must be on the
`teclever` domain. If --password is omitted, you are prompted (hidden input). Writes to the
`users` table in parent.db; `remove` also clears that user's sessions.
"""

from __future__ import annotations

import argparse
import datetime
import getpass
import sqlite3
import sys

from bidplus import merge
from bidplus.web import passwords, schema


def _now() -> str:
    return datetime.datetime.now().isoformat(timespec="seconds")


def _connect() -> sqlite3.Connection:
    parent = merge.connect_parent()
    merge.ensure_shared(parent)   # users table
    schema.ensure_web_schema(parent)  # sessions (for remove cascade)
    return parent


def _get_password(args) -> str:
    pw = args.password or getpass.getpass("Password: ")
    if not pw or len(pw) < 6:
        sys.exit("error: password must be at least 6 characters")
    return pw


def cmd_add(args) -> int:
    email = args.email.strip().lower()
    if not passwords.is_teclever_email(email):
        sys.exit(f"error: {email!r} is not a teclever-domain email")
    parent = _connect()
    if parent.execute("SELECT 1 FROM users WHERE username=?", (email,)).fetchone():
        sys.exit(f"error: user {email!r} already exists (use 'edit' to change password)")
    parent.execute(
        "INSERT INTO users (username, password_hash, created_at) VALUES (?, ?, ?)",
        (email, passwords.hash_password(_get_password(args)), _now()))
    parent.commit()
    print(f"added {email}")
    return 0


def cmd_edit(args) -> int:
    email = args.email.strip().lower()
    parent = _connect()
    row = parent.execute("SELECT id FROM users WHERE username=?", (email,)).fetchone()
    if row is None:
        sys.exit(f"error: no user {email!r}")
    parent.execute("UPDATE users SET password_hash=? WHERE username=?",
                   (passwords.hash_password(_get_password(args)), email))
    parent.execute("DELETE FROM sessions WHERE user_id=?", (row[0],))  # force re-login
    parent.commit()
    print(f"updated password for {email} (existing sessions revoked)")
    return 0


def cmd_remove(args) -> int:
    email = args.email.strip().lower()
    parent = _connect()
    row = parent.execute("SELECT id FROM users WHERE username=?", (email,)).fetchone()
    if row is None:
        sys.exit(f"error: no user {email!r}")
    parent.execute("DELETE FROM sessions WHERE user_id=?", (row[0],))
    parent.execute("DELETE FROM users WHERE id=?", (row[0],))
    parent.commit()
    print(f"removed {email}")
    return 0


def cmd_list(args) -> int:
    parent = _connect()
    rows = parent.execute(
        "SELECT id, username, created_at FROM users ORDER BY id").fetchall()
    if not rows:
        print("(no users)")
        return 0
    for r in rows:
        print(f"  {r[0]:>3}  {r[1]:<40}  {r[2] or ''}")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m bidplus.users", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)
    for name in ("add", "edit"):
        sp = sub.add_parser(name)
        sp.add_argument("email")
        sp.add_argument("--password", help="set non-interactively (else prompted)")
        sp.set_defaults(func=cmd_add if name == "add" else cmd_edit)
    sp = sub.add_parser("remove"); sp.add_argument("email"); sp.set_defaults(func=cmd_remove)
    sub.add_parser("list").set_defaults(func=cmd_list)
    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
