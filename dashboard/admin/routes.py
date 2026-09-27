"""Protected administration pages in the existing dashboard application."""

import asyncio
import html
import json
import os
import secrets
from pathlib import Path
from urllib.parse import parse_qs

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from .operators import read_operators
from .security import (
    LOGIN_CSRF_COOKIE, LOGIN_CSRF_LIFETIME, SESSION_COOKIE, LoginLimiter,
    csrf_digest, new_login_csrf, password_hash, password_valid, session_digest,
    valid_login_csrf,
)
from .storage import AdminStore, SESSION_LIFETIME


router = APIRouter(prefix="/admin")
TEMPLATES = Path(__file__).parent / "templates"
DEFAULT_CONFIG_PATH = Path(__file__).parents[2] / "config" / "config.json"


def initialize_admin(app):
    store = AdminStore(Path(__file__).parents[1] / "data")
    store.initialize()
    app.state.admin_store = store
    app.state.admin_limiter = LoginLimiter()
    app.state.admin_hash_semaphore = asyncio.Semaphore(2)
    app.state.admin_dummy_hash = password_hash(secrets.token_urlsafe(32))


def _store(request):
    return request.app.state.admin_store


def _secure_cookie():
    return os.environ.get("BUENODMR_ADMIN_COOKIE_SECURE") == "1"


def _response(content, status_code=200):
    response = HTMLResponse(content, status_code=status_code)
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Content-Security-Policy"] = (
        "default-src 'none'; style-src 'self'; img-src 'self'; "
        "form-action 'self'; base-uri 'none'; frame-ancestors 'none'"
    )
    return response


def _redirect(url):
    response = RedirectResponse(url, status_code=303)
    response.headers["Cache-Control"] = "no-store"
    return response


def _admin(request):
    token = request.cookies.get(SESSION_COOKIE, "")
    if not token or len(token) > 128:
        return None
    try:
        digest = session_digest(_store(request).secret, token)
    except UnicodeError:
        return None
    admin = _store(request).get_session_admin(digest)
    return admin if admin and admin["role"] == "admin" else None


async def _form(request):
    if not request.headers.get("content-type", "").lower().startswith("application/x-www-form-urlencoded"):
        return None
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > 16384:
            return None
    try:
        pairs = parse_qs(body.decode("utf-8"), keep_blank_values=True, strict_parsing=True)
    except (UnicodeError, ValueError):
        return None
    return {key: values[0] for key, values in pairs.items() if len(values) == 1}


def _login_page(request, error="", status_code=200):
    store = _store(request)
    nonce, token = new_login_csrf(store.secret)
    template = (TEMPLATES / "login.html").read_text(encoding="utf-8")
    page = template.replace("{{CSRF}}", token).replace("{{ERROR}}", html.escape(error))
    response = _response(page, status_code)
    response.set_cookie(
        LOGIN_CSRF_COOKIE, nonce, max_age=LOGIN_CSRF_LIFETIME, path="/admin/login",
        httponly=True, secure=_secure_cookie(), samesite="lax",
    )
    return response


def _client_ip(request):
    return (request.client.host if request.client else "unknown")[:128]


@router.get("/login")
async def login_page(request: Request):
    if _admin(request):
        return _redirect("/admin")
    return _login_page(request)


@router.post("/login")
async def login(request: Request):
    form = await _form(request)
    store = _store(request)
    csrf = form.get("csrf", "") if form else ""
    if not valid_login_csrf(store.secret, request.cookies.get(LOGIN_CSRF_COOKIE), csrf):
        store.audit(None, None, "admin_login_failure", False, _client_ip(request))
        return _login_page(request, "Invalid form. Please try again.", 403)

    username = form.get("username", "").strip().upper()[:64]
    password = form.get("password", "")
    ip = _client_ip(request)
    limiter = request.app.state.admin_limiter
    if limiter.limited(ip, username):
        store.audit(None, username, "admin_login_failure", False, ip)
        return _login_page(request, "Too many attempts. Try again later.", 429)
    limiter.failure(ip, username)
    admin = store.get_admin(username) if username else None
    if len(password) > 1024:
        valid = False
    else:
        # Unknown accounts still perform a password verification to limit enumeration.
        dummy_hash = request.app.state.admin_dummy_hash
        async with request.app.state.admin_hash_semaphore:
            valid = await asyncio.to_thread(password_valid, admin["password_hash"] if admin else dummy_hash, password)
    if not admin or not valid or admin["role"] != "admin":
        store.audit(admin["id"] if admin else None, username, "admin_login_failure", False, ip)
        return _login_page(request, "Invalid username or password.", 401)

    limiter.success(ip, username)
    token = secrets.token_urlsafe(32)
    store.create_session(session_digest(store.secret, token), admin["id"])
    store.audit(admin["id"], admin["username"], "admin_login_success", True, ip)
    response = _redirect("/admin")
    response.set_cookie(
        SESSION_COOKIE, token, max_age=SESSION_LIFETIME, path="/admin",
        httponly=True, secure=_secure_cookie(), samesite="lax",
    )
    response.delete_cookie(LOGIN_CSRF_COOKIE, path="/admin/login")
    return response


@router.get("")
@router.get("/")
async def admin_home(request: Request):
    admin = _admin(request)
    if not admin:
        return _redirect("/admin/login")
    config_path = getattr(request.app.state, "admin_hblink_config_path", DEFAULT_CONFIG_PATH)
    try:
        operators = read_operators(config_path)
    except (OSError, ValueError, TypeError, KeyError):
        return _response("Operator configuration unavailable", 503)
    rows = []
    for operator in operators:
        name = html.escape(operator["name"])
        if operator["base_id"] is not None:
            details = (f"<span>Base DMR ID: {operator['base_id']}</span>"
                       f"<span>ESSID: {operator['essid']}</span>"
                       f"<span>Range: {operator['range']}</span>")
        else:
            raw = html.escape(json.dumps(operator["match"], ensure_ascii=True))
            details = f"<span>Match: <code>{raw}</code></span>"
        rows.append(f'<article class="operator"><div><strong>{name}</strong><small>Authorized</small></div>'
                    f'<div class="operator-details">{details}</div></article>')
    template = (TEMPLATES / "index.html").read_text(encoding="utf-8")
    page = (template.replace("{{USERNAME}}", html.escape(admin["username"]))
            .replace("{{OPERATORS}}", "".join(rows) or "<p>No configured patterns.</p>")
            .replace("{{CSRF}}", csrf_digest(_store(request).secret, "logout", request.cookies[SESSION_COOKIE])))
    return _response(page)


@router.post("/logout")
async def logout(request: Request):
    admin = _admin(request)
    if not admin:
        return _redirect("/admin/login")
    form = await _form(request)
    expected = csrf_digest(_store(request).secret, "logout", request.cookies[SESSION_COOKIE])
    if not form or not secrets.compare_digest(form.get("csrf", ""), expected):
        return _response("Invalid form", 403)
    _store(request).delete_session(session_digest(_store(request).secret, request.cookies[SESSION_COOKIE]))
    _store(request).audit(admin["id"], admin["username"], "admin_logout", True, _client_ip(request))
    response = _redirect("/admin/login")
    response.delete_cookie(SESSION_COOKIE, path="/admin")
    return response
