"""
The web app is plain static files served by the same FastAPI process as the
API. These tests pin the things that fail silently otherwise: the strict
Content-Security-Policy (an inline script/style would just stop working in the
browser), the security headers, the public docs being off, API routes winning
over the static mount, and the length limits that keep a public API from being
fed megabyte-sized "profile" fields.
"""
import asyncio
import re

from fastapi.testclient import TestClient

import database.db as db
from api.deps import get_current_user
from api.main import WEB_DIR, app

client = TestClient(app)


def test_index_is_served_with_the_strict_csp_and_security_headers():
    resp = client.get("/")
    assert resp.status_code == 200 and "Мой Доктор" in resp.text
    csp = resp.headers["content-security-policy"]
    assert "script-src 'self'" in csp and "style-src 'self'" in csp
    assert "unsafe-inline" not in csp and "unsafe-eval" not in csp
    assert "frame-ancestors 'none'" in csp
    assert resp.headers["x-content-type-options"] == "nosniff"
    assert resp.headers["x-frame-options"] == "DENY"
    assert resp.headers["cache-control"] == "no-cache"


def test_static_assets_and_privacy_page_exist():
    for path, kind in [("/app.js", "javascript"), ("/style.css", "css"), ("/privacy.html", "html")]:
        resp = client.get(path)
        assert resp.status_code == 200 and kind in resp.headers["content-type"], path
    assert client.get("/nope.html").status_code == 404


def test_api_routes_win_over_the_static_mount_and_are_never_cached():
    health = client.get("/health")
    assert health.json() == {"status": "ok"}
    unauth = client.get("/me")
    assert unauth.status_code in (401, 403)
    assert unauth.headers["content-type"].startswith("application/json")
    assert unauth.headers["cache-control"] == "no-store"


def test_interactive_docs_are_off_by_default():
    assert client.get("/docs").status_code == 404
    assert client.get("/openapi.json").status_code == 404


def test_the_pages_obey_their_own_csp():
    """Nothing inline: no <script> bodies, no style="" attributes, no event-handler
    attributes, and the script never builds markup from strings."""
    html = (WEB_DIR / "index.html").read_text(encoding="utf-8")
    privacy = (WEB_DIR / "privacy.html").read_text(encoding="utf-8")
    js = (WEB_DIR / "app.js").read_text(encoding="utf-8")
    for page in (html, privacy):
        assert not re.search(r"<script(?![^>]*\bsrc=)", page)
        assert not re.search(r"\sstyle\s*=", page)
        assert not re.search(r"\son[a-z]+\s*=", page)
        assert "<style" not in page
    for banned in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(", "new Function"):
        assert banned not in js, banned
    assert not re.search(r"setAttribute\(\s*['\"]style", js)


def test_every_endpoint_the_web_app_calls_exists():
    js = (WEB_DIR / "app.js").read_text(encoding="utf-8")
    known = {r.path.split("{")[0].rstrip("/") for r in app.routes if hasattr(r, "methods")}
    called = {p.rstrip("/") for p in re.findall(r"api\(\s*[`'](/[a-z\-/]+)", js)}
    assert len(called) >= 15, called                      # the pattern really found the calls
    assert called <= known, sorted(called - known)


# ── Length limits on the public API ─────────────────────────────────────────

def _signed_in(tmp_path):
    db.DATABASE_PATH = str(tmp_path / "limits.db")

    async def setup():
        await db.init_db()
        return await db.get_or_create_user_by_email("limits@example.com")

    uid = asyncio.run(setup())
    app.dependency_overrides[get_current_user] = lambda: uid
    return uid


def test_oversized_profile_and_family_fields_are_rejected(tmp_path):
    _signed_in(tmp_path)
    try:
        ok = {"gender": "female", "age_range": "18_30"}
        assert client.put("/me/profile", json=ok).status_code == 200
        assert client.put("/me/profile", json={**ok, "allergies": "а" * 501}).status_code == 422
        assert client.put("/me/profile", json={**ok, "gender": "x" * 51}).status_code == 422
        assert client.patch("/me/profile", json={"field": "allergies", "value": "а" * 501}).status_code == 422
        assert client.post("/family", json={"name": "а" * 101, "relation": "сын"}).status_code == 422
        assert client.post("/family", json={"name": "", "relation": "сын"}).status_code == 422
        assert client.post("/family", json={"name": "Ваня", "relation": "сын"}).status_code == 200
    finally:
        app.dependency_overrides.clear()
