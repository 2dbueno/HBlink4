"""Transactional operator changes with atomic config apply and recovery."""

import json
import os
import pathlib
import signal
import sqlite3
import stat
import subprocess
import tempfile
import threading
import time
from contextlib import closing, contextmanager
from datetime import datetime, timezone

from .operators import (
    OperatorValidationError, build_config, config_matches_operators,
    public_operator, validate_collection, validate_operator,
)

try:
    import fcntl
except ImportError:  # Windows development; SQLite still locks across processes.
    fcntl = None
try:
    import pwd
except ImportError:  # Windows development uses an injected restarter in tests.
    pwd = None


class ApplyError(RuntimeError):
    pass


class BusyError(ApplyError):
    pass


class DriftError(ApplyError):
    pass


class RollbackError(ApplyError):
    pass


def _fsync_dir(path):
    if hasattr(os, "O_DIRECTORY"):
        fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


class HblinkRestarter:
    """Signal only the fixed hblink4 unit's own process; systemd restarts it."""

    UNIT = "hblink4"

    @classmethod
    def _state(cls):
        result = subprocess.check_output(
            ["systemctl", "show", cls.UNIT, "-p", "User", "-p", "Restart",
             "-p", "ActiveState", "-p", "MainPID", "--no-pager"], text=True,
            timeout=5,
        )
        return dict(line.split("=", 1) for line in result.splitlines() if "=" in line)

    def restart(self):
        before = self._state()
        if (pwd is None or before.get("User") != pwd.getpwuid(os.getuid()).pw_name
                or before.get("Restart") != "always"):
            raise ApplyError("HBlink4 service permissions or restart policy changed.")
        previous = int(before.get("MainPID", "0"))
        if previous > 0 and before.get("ActiveState") == "active":
            if pathlib.Path(f"/proc/{previous}").stat().st_uid != os.getuid():
                raise ApplyError("HBlink4 process owner changed.")
            os.kill(previous, signal.SIGTERM)
        deadline = time.monotonic() + 70
        while time.monotonic() < deadline:
            current = self._state()
            pid = int(current.get("MainPID", "0"))
            if current.get("ActiveState") == "active" and pid > 0 and pid != previous:
                time.sleep(8)
                stable = self._state()
                if stable.get("ActiveState") == "active" and int(stable.get("MainPID", "0")) == pid:
                    return
            time.sleep(1)
        raise ApplyError("HBlink4 did not remain active after restart.")


class OperatorManager:
    def __init__(self, store, config_path, backup_dir, restarter=None):
        self.store = store
        self.config_path = pathlib.Path(config_path)
        self.backup_dir = pathlib.Path(backup_dir)
        self.restarter = restarter or HblinkRestarter()
        self.marker_path = store.data_dir / "config_apply_pending.json"
        self.lock_path = store.data_dir / "admin_apply.lock"
        self._thread_lock = threading.Lock()

    @contextmanager
    def _locked(self):
        if not self._thread_lock.acquire(blocking=False):
            raise BusyError("Configuration update already in progress.")
        fd = None
        try:
            fd = os.open(self.lock_path, os.O_RDWR | os.O_CREAT, 0o600)
            if fcntl is not None:
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError as exc:
                    raise BusyError("Configuration update already in progress.") from exc
            yield
        finally:
            if fd is not None:
                if fcntl is not None:
                    fcntl.flock(fd, fcntl.LOCK_UN)
                os.close(fd)
            self._thread_lock.release()

    def _config(self):
        with self.config_path.open(encoding="utf-8") as source:
            return json.load(source)

    def initialize(self):
        with self._locked():
            self.store.import_operators(self.config_path)
            self._recover_pending()
            if not config_matches_operators(self._config(), self.store.list_operators()):
                raise DriftError("Operator database and HBlink4 config differ.")

    def _write_marker(self, backup):
        fd, temp = tempfile.mkstemp(prefix="apply-marker-", suffix=".tmp", dir=self.store.data_dir)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as dest:
                json.dump({"backup": str(backup)}, dest)
                dest.flush()
                os.fchmod(dest.fileno(), 0o600)
                os.fsync(dest.fileno())
            os.replace(temp, self.marker_path)
            _fsync_dir(self.store.data_dir)
        finally:
            pathlib.Path(temp).unlink(missing_ok=True)

    def _clear_marker(self):
        self.marker_path.unlink(missing_ok=True)
        _fsync_dir(self.store.data_dir)

    def _recover_pending(self):
        if not self.marker_path.exists():
            return
        marker = json.loads(self.marker_path.read_text(encoding="utf-8"))
        backup = pathlib.Path(marker["backup"])
        if backup.resolve().parent != self.backup_dir.resolve() or not backup.name.startswith("config-"):
            raise RollbackError("Invalid pending backup path.")
        if config_matches_operators(self._config(), self.store.list_operators()):
            self._clear_marker()
            return
        self._expected_config_bytes = self.config_path.read_bytes()
        self._replace_config(backup.read_bytes())
        self.restarter.restart()
        if not config_matches_operators(self._config(), self.store.list_operators()):
            raise RollbackError("Recovery did not restore the previous ACL.")
        self._clear_marker()

    def _backup(self, original):
        self.backup_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        if self.backup_dir.stat().st_dev != self.config_path.parent.stat().st_dev:
            raise ApplyError("Backup directory must share a filesystem with the config.")
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        path = self.backup_dir / f"config-{stamp}.json.bak"
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as output:
            output.write(original)
            output.flush()
            os.fsync(output.fileno())
        if path.read_bytes() != original:
            raise ApplyError("Configuration backup could not be verified.")
        _fsync_dir(self.backup_dir)
        return path

    def _replace_config(self, contents):
        previous = self.config_path.stat()
        fd, temp = tempfile.mkstemp(prefix="config-stage-", suffix=".tmp", dir=self.backup_dir)
        try:
            with os.fdopen(fd, "wb") as output:
                output.write(contents)
                output.flush()
                os.fchmod(output.fileno(), stat.S_IMODE(previous.st_mode))
                if hasattr(os, "fchown"):
                    os.fchown(output.fileno(), previous.st_uid, previous.st_gid)
                os.fsync(output.fileno())
            if self.config_path.read_bytes() != self._expected_config_bytes:
                raise DriftError("HBlink4 config changed during update.")
            os.replace(temp, self.config_path)
            _fsync_dir(self.config_path.parent)
        finally:
            pathlib.Path(temp).unlink(missing_ok=True)

    def _prune_backups(self):
        files = sorted(self.backup_dir.glob("config-*.json.bak"))
        for path in files[:-20]:
            path.unlink()

    def list_operators(self):
        return [public_operator(row) for row in self.store.list_operators()]

    def apply(self, action, operator_id, payload, admin, client_ip=None):
        """Validate, stage, restart, then commit DB. Any failure restores both."""
        with self._locked():
            with closing(self.store._connection()) as db:
                try:
                    db.execute("PRAGMA busy_timeout = 0")
                    db.execute("BEGIN IMMEDIATE")
                except sqlite3.OperationalError as exc:
                    raise BusyError("Configuration update already in progress.") from exc
                backup = None
                operator = None
                event = None
                committed = False
                try:
                    existing = self.store.operator_rows(db)
                    current = self._config()
                    if not config_matches_operators(current, existing):
                        raise DriftError("Operator database and HBlink4 config differ.")
                    proposed, operator, event = self._propose(action, operator_id, payload, existing)
                    validate_collection(proposed)
                    candidate = build_config(current, proposed).encode("utf-8")
                    original = self.config_path.read_bytes()
                    self._expected_config_bytes = original
                    if json.loads(original) != current:
                        raise DriftError("HBlink4 config changed during update.")
                    backup = self._backup(original)
                    self._write_marker(backup)
                    self._replace_config(candidate)
                    self.restarter.restart()
                    self._write_rows(db, action, operator_id, operator)
                    self.store._audit(db, admin["id"], admin["username"], event, True,
                                      client_ip, operator["callsign"], operator["base_id"])
                    self.store._audit(db, admin["id"], admin["username"], "config_apply_success",
                                      True, client_ip, operator["callsign"], operator["base_id"])
                    db.commit()
                    committed = True
                except BaseException as exc:
                    if committed:
                        raise
                    db.rollback()
                    rolled_back = False
                    if backup is not None and self.config_path.read_bytes() != original:
                        try:
                            self._expected_config_bytes = self.config_path.read_bytes()
                            self._replace_config(backup.read_bytes())
                            self.restarter.restart()
                            rolled_back = True
                        except BaseException as restore_exc:
                            if event and operator:
                                self.store.audit_operator(admin, event, False, operator, client_ip)
                                self.store.audit_operator(admin, "config_apply_failure", False, operator, client_ip)
                                self.store.audit_operator(admin, "config_rollback", False, operator, client_ip)
                            raise RollbackError("Config restore or HBlink4 recovery failed.") from restore_exc
                    if self.marker_path.exists():
                        self._clear_marker()
                    if event and operator:
                        self.store.audit_operator(admin, event, False, operator, client_ip)
                        self.store.audit_operator(admin, "config_apply_failure", False, operator, client_ip)
                        if rolled_back:
                            self.store.audit_operator(admin, "config_rollback", True, operator, client_ip)
                    if isinstance(exc, (OperatorValidationError, DriftError, BusyError)):
                        raise
                    raise ApplyError("Failed to apply configuration. Previous configuration restored.") from exc
                try:
                    self._clear_marker()
                    self._prune_backups()
                except OSError:
                    # A committed change is already live; recovery clears the marker.
                    pass
                return self.list_operators()

    @staticmethod
    def _propose(action, operator_id, payload, existing):
        rows = [dict(row) for row in existing]
        if action == "create":
            item = validate_operator(payload, create=True)
            rows.append(item)
            return rows, item, "operator_created"
        item = next((row for row in rows if row["id"] == operator_id), None)
        if item is None:
            raise OperatorValidationError("Operator not found.")
        if action == "update":
            updated = validate_operator(payload)
            item.update(updated)
            return rows, item, "operator_updated"
        if action in ("enable", "disable"):
            if payload != {}:
                raise OperatorValidationError("Unexpected operator fields.")
            active = action == "enable"
            if item["active"] == active:
                raise OperatorValidationError("Operator already has that status.")
            item["active"] = active
            return rows, item, "operator_enabled" if active else "operator_disabled"
        if action == "delete":
            if payload != {"confirm_callsign": item["callsign"]}:
                raise OperatorValidationError("Deletion requires exact callsign confirmation.")
            rows.remove(item)
            return rows, item, "operator_deleted"
        raise OperatorValidationError("Unsupported operator action.")

    @staticmethod
    def _write_rows(db, action, operator_id, operator):
        now = datetime.now(timezone.utc).isoformat()
        if action == "create":
            db.execute("""
                INSERT INTO operators (callsign, base_id, essid_from, essid_to,
                                       active, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (operator["callsign"], operator["base_id"], operator["essid_from"],
                  operator["essid_to"], int(operator["active"]), now, now))
        elif action == "delete":
            db.execute("DELETE FROM operators WHERE id = ?", (operator_id,))
        else:
            db.execute("""
                UPDATE operators SET callsign = ?, base_id = ?, essid_from = ?,
                    essid_to = ?, active = ?, updated_at = ? WHERE id = ?
            """, (operator["callsign"], operator["base_id"], operator["essid_from"],
                  operator["essid_to"], int(operator["active"]), now, operator_id))
