"""
tiktok_auth.py ― Blueprint do logowania TikTok Sandbox v2 (+ testowy upload).
"""

import os
import requests
from urllib.parse import quote

from flask import (
    Blueprint,
    redirect,
    request,
    flash,
    url_for,
    session,
    jsonify,
    current_app,
)

# ───────────────────────────────────────────────
# Blueprint
# ───────────────────────────────────────────────
tiktok_auth_bp = Blueprint("tiktok_auth", __name__, url_prefix="/tiktok_auth")

# ───────────────────────────────────────────────
# Zmienne środowiskowe  (Heroku Config Vars)
# ───────────────────────────────────────────────
TIKTOK_CLIENT_KEY    = os.getenv("TIKTOK_CLIENT_KEY")       # ★ sandbox client_key
TIKTOK_CLIENT_SECRET = os.getenv("TIKTOK_CLIENT_SECRET")    # ★ sandbox client_secret
TIKTOK_REDIRECT_URI  = os.getenv("TIKTOK_REDIRECT_URI")     # https://…/tiktok_auth/callback

# ───────────────────────────────────────────────
# Sandbox v2 endpointy
# ───────────────────────────────────────────────
TIKTOK_AUTH_URL   = "https://www.tiktok.com/v2/auth/authorize"           # ← bez „/” na końcu
TIKTOK_TOKEN_URL  = "https://open.tiktokapis.com/v2/oauth/token/"
TIKTOK_UPLOAD_URL = "https://open-sandbox.tiktokapis.com/v2/post/publish/video/upload/"

# WAŻNE ▶︎ spacją, NIE przecinkiem ‑ dokładnie tak chce Login Kit v2
SCOPES = "user.info.basic video.upload video.list"

# ───────────────────────────────────────────────
# /login  → przekierowanie do logowania TikToka
# ───────────────────────────────────────────────
@tiktok_auth_bp.route("/login")
def tiktok_login():
    auth_url = (
        f"{TIKTOK_AUTH_URL}"
        f"?client_key={TIKTOK_CLIENT_KEY}"
        f"&redirect_uri={quote(TIKTOK_REDIRECT_URI, safe='')}"
        f"&scope={quote(SCOPES, safe='')}"
        f"&response_type=code"
        f"&state=xyz123"
    )

    # diagnostyka
    current_app.logger.warning("ENV client_key=%r", TIKTOK_CLIENT_KEY)
    current_app.logger.debug("authorize_url = %s", auth_url)

    return redirect(auth_url)

# ───────────────────────────────────────────────
# /callback  → wymiana code → access_token
# ───────────────────────────────────────────────
@tiktok_auth_bp.route("/callback")
def tiktok_callback():
    log   = current_app.logger
    code  = request.args.get("code")
    error = request.args.get("error")

    log.debug("CB  code=%s  error=%s", code, error)

    if error:
        flash(f"TikTok zwrócił błąd: {error}", "error")
        return redirect(url_for("automation.automation_tiktok"))
    if not code:
        flash("Brak parametru code.", "error")
        return redirect(url_for("automation.automation_tiktok"))

    resp = requests.post(
        TIKTOK_TOKEN_URL,
        data={
            "client_key":    TIKTOK_CLIENT_KEY,
            "client_secret": TIKTOK_CLIENT_SECRET,
            "code":          code,
            "grant_type":    "authorization_code",
            "redirect_uri":  TIKTOK_REDIRECT_URI,
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=10,
    )

    log.debug("token_resp %s  %s", resp.status_code, resp.text[:400])

    if resp.status_code != 200:
        flash("Błąd sieci / TikToka.", "error")
        return redirect(url_for("automation.automation_tiktok"))

    data = resp.json().get("data", {})
    if data.get("error_code"):
        flash(f"TikTok: {data.get('description','unknown')}", "error")
        return redirect(url_for("automation.automation_tiktok"))

    # — sukces —
    session["tiktok_access_token"] = data["access_token"]
    session["tiktok_open_id"]      = data["open_id"]

    flash("Połączono z TikTok (Sandbox).", "success")
    return redirect(url_for("automation.automation_tiktok"))

# ───────────────────────────────────────────────
# /test_upload  → push_by_file do Content Posting API
# ───────────────────────────────────────────────
@tiktok_auth_bp.route("/test_upload")
def tiktok_test_upload():
    """Wysyła plik test.mp4 jako draft na konto w Sandboxie."""
    access_token = session.get("tiktok_access_token")
    if not access_token:
        flash("Najpierw zaloguj się przez TikTok.", "error")
        return redirect(url_for("automation.automation_tiktok"))

    video_file_path = "test.mp4"

    try:
        with open(video_file_path, "rb") as f:
            resp = requests.post(
                TIKTOK_UPLOAD_URL,
                files={"video": f},
                headers={"Authorization": f"Bearer {access_token}"},
                timeout=30,
            )
        return jsonify(resp.json())
    except FileNotFoundError:
        return "Brak pliku test.mp4 w katalogu aplikacji."
