import os
import requests
from urllib.parse import quote_plus
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

# ────────────────────────────────────────────────────────────────────────────────
# Blueprint
# ────────────────────────────────────────────────────────────────────────────────
tiktok_auth_bp = Blueprint("tiktok_auth", __name__, url_prefix="/tiktok_auth")

# ────────────────────────────────────────────────────────────────────────────────
# Heroku Config Vars
# ────────────────────────────────────────────────────────────────────────────────
TIKTOK_CLIENT_KEY    = os.getenv("TIKTOK_CLIENT_KEY")
TIKTOK_CLIENT_SECRET = os.getenv("TIKTOK_CLIENT_SECRET")
TIKTOK_REDIRECT_URI  = os.getenv("TIKTOK_REDIRECT_URI")

# ────────────────────────────────────────────────────────────────────────────────
# SANDBOX v2 Endpoints (UWAGA: sandboxowa domena!)
# ────────────────────────────────────────────────────────────────────────────────
TIKTOK_AUTH_URL  = "https://www.tiktok.com/v2/auth/authorize"   
TIKTOK_TOKEN_URL = "https://open-sandbox.tiktokapis.com/v2/oauth/token"
TIKTOK_UPLOAD_URL = "https://open-sandbox.tiktokapis.com/v2/post/publish/video/upload"

SCOPES = "user.info.basic,video.upload,video.list"

# ────────────────────────────────────────────────────────────────────────────────
# /login → Redirect do TikToka (Sandbox)
# ────────────────────────────────────────────────────────────────────────────────
@tiktok_auth_bp.route("/login")
def tiktok_login():
    # Zaloguj w logach, co naprawdę bierze z ENV:
    current_app.logger.warning("ENV client_key = %r", TIKTOK_CLIENT_KEY)

    params = {
        "client_key":    TIKTOK_CLIENT_KEY,
        "redirect_uri":  quote_plus(TIKTOK_REDIRECT_URI, safe=""),
        "scope":         quote_plus(SCOPES, safe=""),
        "response_type": "code",
        "state":         "xyz123",
    }
    # Zbuduj URL ręcznie, by mieć pełną kontrolę:
    auth_url = (
        f"{TIKTOK_AUTH_URL}"
        f"?client_key={params['client_key']}"
        f"&redirect_uri={params['redirect_uri']}"
        f"&scope={params['scope']}"
        f"&response_type={params['response_type']}"
        f"&state={params['state']}"
    )

    current_app.logger.debug("authorize_url = %s", auth_url)
    return redirect(auth_url)

# ────────────────────────────────────────────────────────────────────────────────
# /callback → wymiana code → access_token
# ────────────────────────────────────────────────────────────────────────────────
@tiktok_auth_bp.route("/callback")
def tiktok_callback():
    log = current_app.logger
    code  = request.args.get("code")
    error = request.args.get("error")

    log.debug("CB callback: code=%s error=%s", code, error)
    if error:
        flash(f"TikTok zwrócił błąd: {error}", "error")
        return redirect(url_for("automation.automation_tiktok"))
    if not code:
        flash("Brak parametru `code`.", "error")
        return redirect(url_for("automation.automation_tiktok"))

    # Wymiana na token
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
    log.debug("token_resp %s %s", resp.status_code, resp.text[:300])

    if resp.status_code != 200:
        flash("Błąd sieci / TikToka (token).", "error")
        return redirect(url_for("automation.automation_tiktok"))
    data = resp.json().get("data", {})
    if data.get("error_code", 0) != 0:
        flash(f"TikTok zwrócił błąd: {data.get('description','unknown')}", "error")
        return redirect(url_for("automation.automation_tiktok"))

    # Sukces!
    session["tiktok_access_token"] = data["access_token"]
    session["tiktok_open_id"]      = data["open_id"]
    flash("Połączono z TikTok (Sandbox).", "success")
    return redirect(url_for("automation.automation_tiktok"))

# ────────────────────────────────────────────────────────────────────────────────
# /test_upload → push_by_file do Content Posting API
# ────────────────────────────────────────────────────────────────────────────────
@tiktok_auth_bp.route("/test_upload")
def tiktok_test_upload():
    access_token = session.get("tiktok_access_token")
    if not access_token:
        flash("Najpierw zaloguj się przez TikTok.", "error")
        return redirect(url_for("automation.automation_tiktok"))

    try:
        with open("test.mp4", "rb") as f:
            resp = requests.post(
                TIKTOK_UPLOAD_URL,
                files={"video": f},
                headers={"Authorization": f"Bearer {access_token}"},
                timeout=30,
            )
        return jsonify(resp.json())
    except FileNotFoundError:
        return "Brak pliku test.mp4 w katalogu aplikacji."
