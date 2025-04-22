import os
import requests
from urllib.parse import quote_plus
from flask import (
    Blueprint, redirect, request, flash,
    url_for, session, jsonify, current_app
)

tiktok_auth_bp = Blueprint("tiktok_auth", __name__, url_prefix="/tiktok_auth")


# Pobierz z Heroku Config Vars
TIKTOK_CLIENT_KEY    = os.getenv("TIKTOK_CLIENT_KEY")
TIKTOK_CLIENT_SECRET = os.getenv("TIKTOK_CLIENT_SECRET")
TIKTOK_REDIRECT_URI  = os.getenv("TIKTOK_REDIRECT_URI")

# Sandbox v2 endpoints
AUTH_URL   = "https://sandbox-open-api.tiktok.com/platform/oauth/connect"
TOKEN_URL  = "https://sandbox-open-api.tiktok.com/oauth/access_token"
UPLOAD_URL = "https://open-sandbox.tiktokapis.com/v2/post/publish/video/upload"
SCOPES     = "user.info.basic,video.upload,video.list"

@bp.route("/login")
def login():
    # dla pewności w logach
    current_app.logger.warning("ENV client_key = %r", TIKTOK_CLIENT_KEY)

    auth_url = (
        f"{AUTH_URL}"
        f"?client_key={TIKTOK_CLIENT_KEY}"
        f"&redirect_uri={quote_plus(TIKTOK_REDIRECT_URI)}"
        f"&scope={quote_plus(SCOPES)}"
        f"&response_type=code"
        f"&state=xyz123"
    )
    current_app.logger.debug("authorize_url = %s", auth_url)
    return redirect(auth_url)

@bp.route("/callback")
def callback():
    log = current_app.logger
    code  = request.args.get("code")
    error = request.args.get("error")

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
    log.debug("token_resp %s %s", resp.status_code, resp.text[:200])

    data = resp.json().get("data", {})
    if resp.status_code != 200 or data.get("error_code"):
        flash(f"TikTok: {data.get('description','unknown')}", "error")
        return redirect(url_for("automation.automation_tiktok"))

    session["tiktok_access_token"] = data["access_token"]
    session["tiktok_open_id"]      = data["open_id"]
    flash("Połączono z TikTok (Sandbox).", "success")
    return redirect(url_for("automation.automation_tiktok"))

@bp.route("/test_upload")
def test_upload():
    token = session.get("tiktok_access_token")
    if not token:
        flash("Najpierw zaloguj się przez TikTok.", "error")
        return redirect(url_for("automation.automation_tiktok"))

    try:
        with open("test.mp4", "rb") as f:
            r = requests.post(
                UPLOAD_URL,
                files={"video": f},
                headers={"Authorization": f"Bearer {token}"},
                timeout=30,
            )
        return jsonify(r.json())
    except FileNotFoundError:
        return "Brak pliku test.mp4."
