"""Small SQLite store for administrative identities and sessions."""

import os
import secrets
import sqlite3
import time
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path


SESSION_LIFETIME = 8 * 60 * 60


class AdminStore:
    def __init__(self, data_dir: Path):
        self.data_dir = Path(data_dir)
        self.db_path = self.data_dir / "admin.sqlite3"
        self.key_path = self.data_dir / "admin_session.key"
        self.secret = None

    def initialize(self):
        self.data_dir.mkdir(parents=True, exist_ok=True)
        if not self.key_path.exists():
            try:
                fd = os.open(self.key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            except FileExistsError:
                pass
            else:
                with os.fdopen(fd, "wb") as key_file:
                    key_file.write(secrets.token_bytes(32))
                    key_file.flush()
                    os.fsync(key_file.fileno())
        if self.key_path.is_symlink():
            raise RuntimeError("Admin session key must not be a symlink")
        self.secret = self.key_path.read_bytes()
        if len(self.secret) != 32:
            raise RuntimeError("Admin session key must contain 32 bytes")
        os.chmod(self.key_path, 0o600)

        if self.db_path.is_symlink():
            raise RuntimeError("Admin database must not be a symlink")
        try:
            fd = os.open(self.db_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            pass
        else:
            os.close(fd)
        os.chmod(self.db_path, 0o600)
        with closing(self._connection()) as db, db:
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if version > 1:
                raise RuntimeError("Admin database schema is newer than this dashboard")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS admins (
                    id INTEGER PRIMARY KEY,
                    username TEXT NOT NULL UNIQUE COLLATE NOCASE,
                    dmr_id INTEGER NOT NULL,
                    role TEXT NOT NULL CHECK (role IN ('admin', 'operator')),
                    password_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS sessions (
                    token_hash TEXT PRIMARY KEY,
                    admin_id INTEGER NOT NULL REFERENCES admins(id) ON DELETE CASCADE,
                    expires_at INTEGER NOT NULL
                );
                CREATE INDEX IF NOT EXISTS sessions_expiry ON sessions(expires_at);
                CREATE TABLE IF NOT EXISTS audit_log (
                    id INTEGER PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    admin_id INTEGER,
                    username TEXT,
                    action TEXT NOT NULL,
                    success INTEGER NOT NULL,
                    client_ip TEXT
                );
                PRAGMA user_version = 1;
            """)

    def _connection(self):
        db = sqlite3.connect(self.db_path, timeout=5)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys = ON")
        return db

    def get_admin(self, username):
        with closing(self._connection()) as db:
            row = db.execute(
                "SELECT id, username, dmr_id, role, password_hash FROM admins WHERE username = ?",
                (username,),
            ).fetchone()
            return dict(row) if row else None

    def create_or_replace_admin(self, username, dmr_id, password_hash, replace=False):
        with closing(self._connection()) as db, db:
            existing = db.execute("SELECT id FROM admins WHERE username = ?", (username,)).fetchone()
            if existing and not replace:
                raise ValueError("Admin already exists")
            if not existing and db.execute("SELECT COUNT(*) FROM admins").fetchone()[0]:
                raise ValueError("Phase 1 supports only the initial administrator")
            if existing:
                db.execute(
                    "UPDATE admins SET dmr_id = ?, role = 'admin', password_hash = ? WHERE id = ?",
                    (dmr_id, password_hash, existing[0]),
                )
                db.execute("DELETE FROM sessions WHERE admin_id = ?", (existing[0],))
                admin_id = existing[0]
            else:
                admin_id = db.execute(
                    "INSERT INTO admins (username, dmr_id, role, password_hash, created_at) VALUES (?, ?, 'admin', ?, ?)",
                    (username, dmr_id, password_hash, datetime.now(timezone.utc).isoformat()),
                ).lastrowid
            self._audit(db, admin_id, username, "admin_bootstrap", True, None)

    def create_session(self, token_hash, admin_id):
        expires = int(time.time()) + SESSION_LIFETIME
        with closing(self._connection()) as db, db:
            db.execute("DELETE FROM sessions WHERE expires_at <= ?", (int(time.time()),))
            db.execute(
                "INSERT INTO sessions (token_hash, admin_id, expires_at) VALUES (?, ?, ?)",
                (token_hash, admin_id, expires),
            )
        return expires

    def get_session_admin(self, token_hash):
        with closing(self._connection()) as db:
            row = db.execute("""
                SELECT a.id, a.username, a.dmr_id, a.role FROM sessions s
                JOIN admins a ON a.id = s.admin_id
                WHERE s.token_hash = ? AND s.expires_at > ?
            """, (token_hash, int(time.time()))).fetchone()
            return dict(row) if row else None

    def delete_session(self, token_hash):
        with closing(self._connection()) as db, db:
            db.execute("DELETE FROM sessions WHERE token_hash = ?", (token_hash,))

    def audit(self, admin_id, username, action, success, client_ip):
        with closing(self._connection()) as db, db:
            self._audit(db, admin_id, username, action, success, client_ip)

    @staticmethod
    def _audit(db, admin_id, username, action, success, client_ip):
        db.execute(
            "INSERT INTO audit_log (created_at, admin_id, username, action, success, client_ip) VALUES (?, ?, ?, ?, ?, ?)",
            (datetime.now(timezone.utc).isoformat(), admin_id, username, action, int(success), client_ip),
        )
        db.execute("DELETE FROM audit_log WHERE id <= (SELECT MAX(id) - 10000 FROM audit_log)")
