"""Security and read-only behavior of the BuenoDMR administration area."""

import asyncio
import atexit
import json
import re
import sqlite3
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from dashboard.admin.operators import read_operators
from dashboard.admin.routes import router
from dashboard.admin.security import LoginLimiter, SESSION_COOKIE, password_hash, session_digest
from dashboard.admin.storage import AdminStore


PASSWORD = "a-strong-test-password"
DMR_SECRET = "DMR_SECRET_MUST_NOT_APPEAR"
OPERATORS = [
    ("PY2DES", 724287000, 724287099),
    ("PY2PMI", 724015000, 724015099),
    ("PU2MXD", 724011900, 724011999),
    ("PY2IUD", 724002500, 724002599),
]


@pytest.fixture
def admin_site(tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({
        "dynamic_talkgroups": {"enabled": True, "talkgroup": 100, "disconnect_talkgroup": 4100},
        "repeater_configurations": {"patterns": [
            {"name": name, "match": {"id_ranges": [[start, end]]},
             "config": {"passphrase": DMR_SECRET, "trust": False,
                        "slot1_talkgroups": [], "slot2_talkgroups": [100]}}
            for name, start, end in OPERATORS
        ]}
    }), encoding="utf-8")
    original_config = config_path.read_bytes()
    store = AdminStore(tmp_path / "data")
    store.initialize()
    app = FastAPI()
    app.include_router(router)
    app.state.admin_store = store
    app.state.admin_limiter = LoginLimiter()
    app.state.admin_hash_semaphore = asyncio.Semaphore(2)
    app.state.admin_dummy_hash = password_hash("dummy-password-never-used")
    app.state.admin_hblink_config_path = config_path
    with TestClient(app) as client:
        yield client, store, config_path, original_config


def csrf_from(page):
    return re.search(r'name="csrf" value="([^"]+)"', page.text).group(1)


def bootstrap(store):
    store.create_or_replace_admin("PY2DES", 7242870, password_hash(PASSWORD))


def sign_in(client, password=PASSWORD, username="PY2DES"):
    login_page = client.get("/admin/login")
    return client.post("/admin/login", data={
        "username": username, "password": password, "csrf": csrf_from(login_page)
    }, follow_redirects=False)


def test_protected_admin_and_public_dashboard(admin_site):
    client, store, _, _ = admin_site
    response = client.get("/admin", follow_redirects=False)
    assert response.status_code == 303 and response.headers["location"] == "/admin/login"
    assert client.get("/admin/login").status_code == 200
    assert client.get("/admin/login").headers["cache-control"] == "no-store"

    from dashboard import server as dashboard_module
    atexit.unregister(dashboard_module.save_persistent_data)
    dashboard_app = dashboard_module.app
    public_client = TestClient(dashboard_app)
    assert public_client.get("/").status_code == 200
    assert public_client.get("/api/stats").status_code == 200


def test_login_session_logout_and_audit(admin_site):
    client, store, _, _ = admin_site
    bootstrap(store)
    invalid = sign_in(client, "wrong-password")
    assert invalid.status_code == 401
    assert "Invalid username or password" in invalid.text
    assert client.get("/admin", follow_redirects=False).status_code == 303

    success = sign_in(client)
    assert success.status_code == 303
    assert success.headers["location"] == "/admin"
    cookie = success.headers["set-cookie"]
    assert "HttpOnly" in cookie and "SameSite=lax" in cookie and "Max-Age=" in cookie
    home = client.get("/admin")
    assert home.status_code == 200 and "PY2DES" in home.text
    assert client.get("/admin/").status_code == 200
    assert client.post("/admin/logout", data={"csrf": "wrong"}).status_code == 403
    assert client.get("/admin").status_code == 200
    logout = client.post("/admin/logout", data={"csrf": csrf_from(home)}, follow_redirects=False)
    assert logout.status_code == 303
    assert client.get("/admin", follow_redirects=False).status_code == 303
    with sqlite3.connect(store.db_path) as db:
        actions = [row[0] for row in db.execute("SELECT action FROM audit_log ORDER BY id")]
        assert actions == ["admin_bootstrap", "admin_login_failure", "admin_login_success", "admin_logout"]
        assert db.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 0


def test_hash_bootstrap_identity_and_no_automatic_admins(admin_site):
    _, store, _, _ = admin_site
    with sqlite3.connect(store.db_path) as db:
        assert db.execute("SELECT COUNT(*) FROM admins").fetchone()[0] == 0
    bootstrap(store)
    admin = store.get_admin("PY2DES")
    assert admin["dmr_id"] == 7242870 and admin["role"] == "admin"
    assert admin["password_hash"].startswith("$argon2id$")
    assert PASSWORD not in admin["password_hash"]
    for name, _, _ in OPERATORS[1:]:
        assert store.get_admin(name) is None
    with pytest.raises(ValueError):
        store.create_or_replace_admin("PY2DES", 7242870, password_hash(PASSWORD))
    with pytest.raises(ValueError):
        store.create_or_replace_admin("PY2PMI", 7240150, password_hash(PASSWORD))


def test_csrf_login_and_logout_reject_invalid_tokens(admin_site):
    client, store, _, _ = admin_site
    bootstrap(store)
    assert client.post("/admin/login", data={
        "username": "PY2DES", "password": PASSWORD, "csrf": "invalid"
    }).status_code == 403
    assert client.get("/admin", follow_redirects=False).status_code == 303
    assert sign_in(client).status_code == 303
    assert client.post("/admin/logout", data={"csrf": "invalid"}).status_code == 403
    assert client.post("/admin/logout", data={"csrf": csrf_from(client.get("/admin"))}).status_code == 200


def test_rate_limit_is_bounded_and_rejects_correct_password(admin_site):
    client, store, _, _ = admin_site
    bootstrap(store)
    for _ in range(5):
        assert sign_in(client, "wrong-password").status_code == 401
    assert sign_in(client).status_code == 429
    assert len(client.app.state.admin_limiter.attempts) <= 1024


def test_pattern_projection_and_config_remain_read_only(admin_site):
    client, store, config_path, original_config = admin_site
    bootstrap(store)
    assert sign_in(client).status_code == 303
    operators = read_operators(config_path)
    assert [(o["name"], o["base_id"], o["essid"], o["range"]) for o in operators] == [
        (name, start // 100, "00-99", f"{start}-{end}") for name, start, end in OPERATORS
    ]
    page = client.get("/admin")
    for name, start, end in OPERATORS:
        assert name in page.text and f"{start}-{end}" in page.text
    assert "Read-only configuration" in page.text
    assert DMR_SECRET not in page.text
    assert DMR_SECRET not in json.dumps(operators)
    assert PASSWORD not in page.text
    assert config_path.read_bytes() == original_config


def test_unusual_pattern_shows_only_escaped_match_metadata(admin_site):
    client, store, config_path, _ = admin_site
    config = json.loads(config_path.read_text())
    config["repeater_configurations"]["patterns"].append({
        "name": "<script>alert(1)</script>",
        "match": {"ids": [312001]},
        "config": {"passphrase": DMR_SECRET},
    })
    config_path.write_text(json.dumps(config), encoding="utf-8")
    bootstrap(store)
    assert sign_in(client).status_code == 303
    page = client.get("/admin")
    assert "<script>" not in page.text
    assert "&lt;script&gt;" in page.text
    assert "312001" in page.text
    assert DMR_SECRET not in page.text


def test_session_survives_store_reopen_and_secure_cookie_option(admin_site, monkeypatch):
    client, store, _, _ = admin_site
    bootstrap(store)
    monkeypatch.setenv("BUENODMR_ADMIN_COOKIE_SECURE", "1")
    https_client = TestClient(client.app, base_url="https://testserver")
    success = sign_in(https_client)
    assert success.status_code == 303
    assert "Secure" in success.headers["set-cookie"]
    token = success.headers["set-cookie"].split(f"{SESSION_COOKIE}=", 1)[1].split(";", 1)[0]
    reopened = AdminStore(store.data_dir)
    reopened.initialize()
    assert reopened.secret == store.secret
    assert reopened.get_session_admin(session_digest(reopened.secret, token))["username"] == "PY2DES"


def test_cli_bootstrap_only_py2des_and_requires_explicit_rotation(admin_site, monkeypatch):
    from dashboard import admin_cli

    _, store, _, _ = admin_site
    monkeypatch.setattr(admin_cli, "AdminStore", lambda _path: store)
    monkeypatch.setattr(admin_cli.sys, "stdin", SimpleNamespace(isatty=lambda: True))
    answers = iter((PASSWORD, PASSWORD))
    monkeypatch.setattr(admin_cli.getpass, "getpass", lambda _prompt: next(answers))
    with pytest.raises(SystemExit):
        admin_cli.main(["create-admin", "--username", "PY2PMI", "--dmr-id", "7240150"])
    admin_cli.main(["create-admin", "--username", "PY2DES", "--dmr-id", "7242870"])
    assert store.get_admin("PY2DES") is not None
    with pytest.raises(SystemExit):
        admin_cli.main(["create-admin", "--username", "PY2DES", "--dmr-id", "7242870"])
