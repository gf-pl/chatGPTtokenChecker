import json
import sqlite3
import uuid
from contextlib import contextmanager
from pathlib import Path

DB_PATH = Path("/app/data/usage.db")


@contextmanager
def connection():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    try:
        yield db
        db.commit()
    finally:
        db.close()


def initialize():
    with connection() as db:
        existing = db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='accounts'").fetchone()
        db.execute("""CREATE TABLE IF NOT EXISTS accounts (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            position INTEGER NOT NULL
        )""")
        db.execute("""CREATE TABLE IF NOT EXISTS plan_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id TEXT NOT NULL,
            captured_at INTEGER NOT NULL,
            plan_type TEXT,
            email TEXT,
            limits_json TEXT NOT NULL,
            usage_json TEXT
        )""")
        db.execute("CREATE INDEX IF NOT EXISTS plan_snapshots_account_time ON plan_snapshots(account_id, captured_at DESC)")
        if not existing:
            # The old app stored account1/account2 sign-ins in separate folders.
            # Import only accounts with a saved sign-in folder or readings.
            position = 0
            for number in (1, 2):
                account_id = f"account{number}"
                saved_home = (DB_PATH.parent / account_id).is_dir()
                latest = db.execute(
                    "SELECT email FROM plan_snapshots WHERE account_id=? ORDER BY captured_at DESC,id DESC LIMIT 1",
                    (account_id,),
                ).fetchone()
                if saved_home or latest:
                    name = latest["email"] if latest and latest["email"] else f"Account {number}"
                    db.execute("INSERT INTO accounts (id, name, position) VALUES (?, ?, ?)",
                               (account_id, name, position))
                    position += 1


def list_accounts() -> list[dict[str, str]]:
    with connection() as db:
        rows = db.execute("SELECT id, name FROM accounts ORDER BY position, rowid").fetchall()
    return [dict(row) for row in rows]


def account_exists(account_id: str) -> bool:
    with connection() as db:
        return db.execute("SELECT 1 FROM accounts WHERE id=?", (account_id,)).fetchone() is not None


def create_account(name: str) -> dict[str, str]:
    account = {"id": f"account-{uuid.uuid4().hex}", "name": name}
    with connection() as db:
        position = db.execute("SELECT COALESCE(MAX(position), -1) + 1 FROM accounts").fetchone()[0]
        db.execute("INSERT INTO accounts (id, name, position) VALUES (?, ?, ?)",
                   (account["id"], account["name"], position))
    return account


def delete_account(account_id: str):
    with connection() as db:
        db.execute("DELETE FROM plan_snapshots WHERE account_id=?", (account_id,))
        db.execute("DELETE FROM accounts WHERE id=?", (account_id,))


def save_snapshot(account_id: str, captured_at: int, plan_type: str | None, email: str | None, limits: dict, usage: dict | None):
    with connection() as db:
        db.execute(
            "INSERT INTO plan_snapshots (account_id,captured_at,plan_type,email,limits_json,usage_json) VALUES (?,?,?,?,?,?)",
            (account_id, captured_at, plan_type, email, json.dumps(limits), json.dumps(usage) if usage else None),
        )


def snapshots(account_id: str, limit: int = 50) -> list[dict]:
    with connection() as db:
        rows = db.execute(
            "SELECT captured_at,plan_type,email,limits_json,usage_json FROM plan_snapshots WHERE account_id=? ORDER BY captured_at DESC,id DESC LIMIT ?",
            (account_id, limit),
        ).fetchall()
    return [{"captured_at": row["captured_at"], "plan_type": row["plan_type"], "email": row["email"],
             "limits": json.loads(row["limits_json"]), "usage": json.loads(row["usage_json"]) if row["usage_json"] else None}
            for row in rows]
