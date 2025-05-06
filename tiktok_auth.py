# tiktok_auth.py
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
    current_app,
    jsonify,
)

tiktok_auth_bp = Blueprint(
    "tiktok_auth",
    __name__,
    url_prefix="/tiktok_auth"
)

# ── Zmienne środowiskowe (Heroku: Config Vars) ──────────────────────
TIKTOK_CLIENT_KEY    = os.getenv("TIKTOK_CLIENT_KEY")
TIKTOK_CLIENT_SECRET = os.getenv("TIKTOK_CLIENT_SECRET")
TIKTOK_REDIRECT_URI  = os.getenv("TIKTOK_REDIRECT_URI")

# ── TikTok OAuth Endpoints (Sandbox używa open.tiktokapis.com) ──────
AUTH_URL  = "https://www.tiktok.com/v2/auth/authorize"
TOKEN_URL = "https://open.tiktokapis.com/v2/oauth/token/"

# ⚠️ Pełny zakres – user info + upload wideo
SCOPES = "user.info.basic,video.upload,video.list"

# -------------------------------------------------------------------


@tiktok_auth_bp.route("/login")
def login():
    """Przekierowuje użytkownika do TikTok OAuth (Sandbox)."""
    params = {
        "client_key":    TIKTOK_CLIENT_KEY,
        "redirect_uri":  TIKTOK_REDIRECT_URI,
        "scope":         SCOPES,
        "response_type": "code",
        "state":         "xyz123",
    }
    query = "&".join(f"{k}={quote_plus(v)}" for k, v in params.items())
    return redirect(f"{AUTH_URL}?{query}")


@tiktok_auth_bp.route("/callback")
def callback():
    """Wymienia 'code' na token + open_id i zapisuje je w sesji."""
    if request.args.get("error"):
        flash(f"TikTok error: {request.args['error']}", "error")
        return redirect(url_for("automation.automation_tiktok"))

    code = request.args.get("code")
    if not code:
        flash("Missing code from TikTok.", "error")
        return redirect(url_for("automation.automation_tiktok"))

    try:
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
        resp.raise_for_status()
    except requests.RequestException as e:
        current_app.logger.error("Token request failed: %s", e)
        flash("TikTok token request failed.", "error")
        return redirect(url_for("automation.automation_tiktok"))

    result = resp.json()
    current_app.logger.debug("🎯 Token response JSON: %r", result)

    # Różne wersje API potrafią zwracać dane bezpośrednio lub pod 'data'
    open_id      = result.get("open_id")      or result.get("data", {}).get("open_id")
    access_token = result.get("access_token") or result.get("data", {}).get("access_token")
    scope_str    = result.get("scope")        or result.get("data", {}).get("scope", "")

    if not open_id or not access_token:
        desc = result.get("description") or result.get("message") or "Unknown error"
        flash(f"TikTok token error: {desc}", "error")
        return redirect(url_for("automation.automation_tiktok"))

    session["tiktok_open_id"]      = open_id
    session["tiktok_access_token"] = access_token
    session["tiktok_scopes"]       = scope_str.split()  # np. ['user.info.basic', 'video.upload']

    flash("Zalogowano pomyślnie.", "success")
    return redirect(url_for("automation.automation_tiktok"))


@tiktok_auth_bp.route("/logout")
def logout():
    """Czyści sesję OAuth TikToka (open_id, access_token, scopes)."""
    session.pop("tiktok_open_id", None)
    session.pop("tiktok_access_token", None)
    session.pop("tiktok_scopes", None)
    flash("Wylogowano z TikTok Sandbox.", "success")
    return redirect(url_for("automation.automation_tiktok"))


@tiktok_auth_bp.route("/whoami")
def whoami():
    """Pomocniczy endpoint – zwraca open_id i zakres tokena."""
    return jsonify(
        open_id=session.get("tiktok_open_id"),
        scopes=session.get("tiktok_scopes", []),
    ), 200
