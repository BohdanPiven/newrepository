# tiktok_auth.py  — Blueprint obsługujący Login Kit Sandbox v2 + przykładowy upload
import os
import requests
from urllib.parse import quote_plus
from flask import Blueprint, redirect, request, flash, url_for, session, jsonify, current_app

# ───────────────────────────────────────────────────────────────────────────────
# Nazwa blueprintu musi zgadzać się z tym, co rejestrujesz w app.py
# ───────────────────────────────────────────────────────────────────────────────
tiktok_auth_bp = Blueprint("tiktok_auth", __name__, url_prefix="/tiktok_auth")

# ───────────────────────────────────────────────────────────────────────────────
# Pobierz z Heroku Config Vars
# ───────────────────────────────────────────────────────────────────────────────
TIKTOK_CLIENT_KEY    = os.getenv("TIKTOK_CLIENT_KEY")
TIKTOK_CLIENT_SECRET = os.getenv("TIKTOK_CLIENT_SECRET")
TIKTOK_REDIRECT_URI  = os.getenv("TIKTOK_REDIRECT_URI")

# ───────────────────────────────────────────────────────────────────────────────
# Sandbox v2 endpointy (login/token/upload)
# ───────────────────────────────────────────────────────────────────────────────
AUTH_URL   = "https://www.tiktok.com/v2/auth/authorize"
TOKEN_URL  = "https://open-sandbox.tiktokapis.com/v2/oauth/token/"
UPLOAD_URL = "https://open-sandbox.tiktokapis.com/v2/post/publish/video/upload/"

# dokładnie z przecinkami, bez spacji
SCOPES = "user.info.basic,video.upload,video.list"

# ───────────────────────────────────────────────────────────────────────────────
# 1) /login  → przekierowanie do TikToka
# ───────────────────────────────────────────────────────────────────────────────
@tiktok_auth_bp.route("/login")
def login():
    # sprawdzamy w logach co mamy w env
    current_app.logger.warning("ENV client_key = %r", TIKTOK_CLIENT_KEY)

    authorize_url = (
        f"{AUTH_URL}"
        f"?client_key={TIKTOK_CLIENT_KEY}"
        f"&redirect_uri={quote_plus(TIKTOK_REDIRECT_URI, safe='')}"
        f"&scope={quote_plus(SCOPES, safe='')}"
        f"&response_type=code"
        f"&state=xyz123"
    )
    current_app.logger.debug("authorize_url = %s", authorize_url)
    return redirect(authorize_url)

# ───────────────────────────────────────────────────────────────────────────────
# 2) /callback  → wymiana code na access_token
# ───────────────────────────────────────────────────────────────────────────────
@tiktok_auth_bp.route("/callback")
def callback():
    log   = current_app.logger
    code  = request.args.get("code")
    error = request.args.get("error")

    log.debug("CB  code=%s  error=%s", code, error)

    if error:
        flash(f"TikTok zwrócił błąd: {error}", "error")
        return redirect(url_for("automation.automation_tiktok"))
    if not code:
        flash("Brak parametru code.", "error")
        return redirect(url_for("automation.automation_tiktok"))

    resp = requests.post(
        TOKEN_URL,
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

    try:
        data = resp.json().get("data", {})
    except ValueError:
        flash("Niepoprawna odpowiedź od TikToka.", "error")
        return redirect(url_for("automation.automation_tiktok"))

    if resp.status_code != 200 or data.get("error_code"):
        desc = data.get("description", "unknown")
        flash(f"TikTok zwrócił błąd: {desc}", "error")
        return redirect(url_for("automation.automation_tiktok"))

    # — sukces —
    session["tiktok_access_token"] = data["access_token"]
    session["tiktok_open_id"]      = data["open_id"]
    flash("Połączono z TikTok (Sandbox).", "success")
    return redirect(url_for("automation.automation_tiktok"))

# ───────────────────────────────────────────────────────────────────────────────
# 3) /test_upload  → prosty push_by_file do Content Posting API
# ───────────────────────────────────────────────────────────────────────────────
@tiktok_auth_bp.route("/test_upload")
def test_upload():
    access_token = session.get("tiktok_access_token")
    if not access_token:
        flash("Najpierw zaloguj się przez TikTok.", "error")
        return redirect(url_for("automation.automation_tiktok"))

    try:
        with open("test.mp4", "rb") as f:
            resp = requests.post(
                UPLOAD_URL,
                files={"video": f},
                headers={"Authorization": f"Bearer {access_token}"},
                timeout=30,
            )
        return jsonify(resp.json())
    except FileNotFoundError:
        return "Brak pliku test.mp4 w katalogu aplikacji."
