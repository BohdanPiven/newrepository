# tiktok_auth.py  – Blueprint do Sandbox v2
import os, requests
from urllib.parse import quote_plus
from flask import Blueprint, redirect, request, flash, url_for, session, jsonify, current_app

bp = Blueprint("tiktok_auth", __name__, url_prefix="/tiktok_auth")

TIKTOK_CLIENT_KEY    = os.getenv("TIKTOK_CLIENT_KEY")
TIKTOK_CLIENT_SECRET = os.getenv("TIKTOK_CLIENT_SECRET")
TIKTOK_REDIRECT_URI  = os.getenv("TIKTOK_REDIRECT_URI")

AUTH_URL   = "https://www.tiktok.com/v2/auth/authorize"
TOKEN_URL  = "https://open-sandbox.tiktokapis.com/v2/oauth/token/"
UPLOAD_URL = "https://open-sandbox.tiktokapis.com/v2/post/publish/video/upload/"
SCOPES     = "user.info.basic,video.upload,video.list"      # przecinki!

# ───── /login ──────────────────────────────────────────────
@bp.route("/login")
def login():
    current_app.logger.warning("ENV client_key = %r", TIKTOK_CLIENT_KEY)

    url = (
        f"{AUTH_URL}"
        f"?client_key={TIKTOK_CLIENT_KEY}"
        f"&redirect_uri={quote_plus(TIKTOK_REDIRECT_URI, safe='')}"
        f"&scope={quote_plus(SCOPES, safe='')}"
        f"&response_type=code"
        f"&state=xyz123"
    )
    current_app.logger.debug("authorize_url = %s", url)
    return redirect(url)

# ───── /callback ───────────────────────────────────────────
@bp.route("/callback")
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

    data = resp.json().get("data", {})
    if resp.status_code != 200 or data.get("error_code"):
        flash(f"TikTok: {data.get('description','unknown')}", "error")
        return redirect(url_for("automation.automation_tiktok"))

    session["tiktok_access_token"] = data["access_token"]
    session["tiktok_open_id"]      = data["open_id"]
    flash("Połączono z TikTok (Sandbox).", "success")
    return redirect(url_for("automation.automation_tiktok"))

# ───── /test_upload (opcjonalnie) ──────────────────────────
@bp.route("/test_upload")
def test_upload():
    access_token = session.get("tiktok_access_token")
    if not access_token:
        flash("Najpierw zaloguj się przez TikTok.", "error")
        return redirect(url_for("automation.automation_tiktok"))

    try:
        with open("test.mp4", "rb") as f:
            r = requests.post(
                UPLOAD_URL,
                files={"video": f},
                headers={"Authorization": f"Bearer {access_token}"},
                timeout=30,
            )
        return jsonify(r.json())
    except FileNotFoundError:
        return "Brak pliku test.mp4."
