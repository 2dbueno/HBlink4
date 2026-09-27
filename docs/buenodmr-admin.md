# BuenoDMR administration: phase 1

The existing dashboard remains public at `/`. The separate `/admin` area requires
an administrative account. The DMR network and the admin area use different
credentials. A DMR callsign, base ID, ESSID, hotspot connection, and the shared
DMR passphrase do not grant dashboard access.

Phase 1 is read-only. The operator list is loaded from
`config/config.json` (`repeater_configurations.patterns`) on each `/admin`
request. Only the pattern name and ID matching fields are rendered. The DMR
passphrase is never returned. Patterns representing a contiguous 9-digit
`base + 00..99` range display the base ID and ESSID range; other patterns show
their non-secret match fields without guessing. No browser route writes the
HBlink4 config or restarts the HBlink4 service.

## First administrator

Install `requirements-dashboard.txt` into the dashboard's existing virtual
environment, then run this command **interactively** on the server:

```sh
cd ~/HBlink4
./venv/bin/python -m dashboard.admin_cli create-admin --username PY2DES --dmr-id 7242870
```

The CLI prompts twice for a password of at least 12 characters and never echoes
it. No account is created by dashboard startup or deployment. Phase 1 permits
only PY2DES (base ID 7242870) as an admin. The other authorized DMR operators
receive no admin account. To rotate the password deliberately, rerun the
command with `--replace` and type `PY2DES` at the confirmation prompt. Rotation
invalidates existing sessions.

## Storage and security

`dashboard/data/admin.sqlite3` holds admin accounts, Argon2id password hashes,
server-side session hashes, and audit entries. The schema is initialized
idempotently. `dashboard/data/admin_session.key` is a persistent random HMAC
key for session and CSRF tokens. Both runtime files are ignored by Git and are
created with owner-only permissions on Linux. The key must remain private.

Sessions use random opaque cookies, expire after eight hours, and are deleted
on logout. Cookies are HttpOnly and SameSite=Lax. Login and logout forms require
signed CSRF tokens. Failed login attempts are limited by account and client IP
with bounded in-memory state. The audit log records login successes, failures,
logouts, and initial account creation without passwords, hashes, session tokens,
or DMR passphrases. Audit retention is capped at 10,000 entries.

The current LAN HTTP deployment uses cookies without `Secure`, since that flag
would prevent login over HTTP. Set `BUENODMR_ADMIN_COOKIE_SECURE=1` in the
dashboard service environment when the browser connects through HTTPS. HTTP
does not protect credentials from a network observer; do not expose `/admin`
outside the trusted LAN without HTTPS.

## Backup

Back up both files outside the checkout with restrictive permissions. SQLite's
backup API creates a consistent copy even while the dashboard is running:

```sh
cd ~/HBlink4
./venv/bin/python - <<'PY'
import datetime, os, pathlib, shutil, sqlite3
source = pathlib.Path('dashboard/data')
target = pathlib.Path.home() / 'HBlink4-backup' / ('admin-' + datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ'))
target.mkdir(parents=True, mode=0o700)
with sqlite3.connect(source / 'admin.sqlite3') as db, sqlite3.connect(target / 'admin.sqlite3') as copy:
    db.backup(copy)
os.chmod(target / 'admin.sqlite3', 0o600)
shutil.copyfile(source / 'admin_session.key', target / 'admin_session.key')
os.chmod(target / 'admin_session.key', 0o600)
print(target)
PY
```

Protect the backup like an administrative credential. To restore, stop only the
dashboard, restore the database and key together with owner-only permissions,
and start the dashboard. `config/config.json` is separate and stays read-only
throughout phase 1.
