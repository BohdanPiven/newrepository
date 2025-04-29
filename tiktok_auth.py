# tiktok_auth.py

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
    current_app
)

tiktok_auth_bp = Blueprint(
    "tiktok_auth",
    __name__,
    url_prefix="/tiktok_auth"
)

# ——————————————————————————
# 1) Środowiskowe zmienne (Heroku Config Vars)
# ——————————————————————————
TIKTOK_CLIENT_KEY    = os.getenv("TIKTOK_CLIENT_KEY")
TIKTOK_CLIENT_SECRET = os.getenv("TIKTOK_CLIENT_SECRET")
TIKTOK_REDIRECT_URI  = os.getenv("TIKTOK_REDIRECT_URI")

# ——————————————————————————
# 2) Sandbox OAuth Endpoints
# ——————————————————————————
AUTH_URL         = "https://open.tiktokapis.com/v2/auth/authorize"
TOKEN_URL        = "https://open.tiktokapis.com/v2/oauth/token/"
USER_INFO_URL    = "https://open.tiktokapis.com/v2/user/info/"
VIDEO_UPLOAD_URL = "https://open.tiktokapis.com/v2/post/publish/video/upload/"
VIDEO_LIST_URL   = "https://open.tiktokapis.com/v2/post/publish/video/list/"

# ——————————————————————————
# 3) Scope’y wymagane (dodaj je w Developer Portal → Sandbox → Scopes)
# ——————————————————————————
SCOPES = "user.info.basic video.upload video.list"


@tiktok_auth_bp.route("/login")
def login():
    """
    Przekierowanie użytkownika do TikTok Sandbox OAuth.
    """
    # miejsce, w którym kodujemy spację jako %20 (nie jako +)
    scope_encoded = quote(SCOPES, safe='')

    # kodujemy też redirect_uri
    redirect_encoded = quote(TIKTOK_REDIRECT_URI, safe='')

    authorize_url = (
        f"{AUTH_URL}"
        f"?client_key={quote(TIKTOK_CLIENT_KEY, safe='')}"
        f"&redirect_uri={redirect_encoded}"
        f"&scope={scope_encoded}"
        f"&response_type=code"
        f"&state=xyz123"
    )
    return redirect(authorize_url)


@tiktok_auth_bp.route("/callback")
def callback():
    """
    Odbiór kodu, wymiana na access_token + open_id i zapis w sesji.
    """
    if request.args.get("error"):
        flash(f"TikTok error: {request.args['error']}", "error")
        return redirect(url_for("automation.automation_tiktok"))

    code = request.args.get("code")
    if not code:
        flash("Brak parametru code od TikToka.", "error")
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
    except Exception as e:
        current_app.logger.error("Token request failed: %s", e)
        flash("Błąd podczas pobierania tokenu.", "error")
        return redirect(url_for("automation.automation_tiktok"))

    payload = resp.json().get("data", resp.json())
    open_id      = payload.get("open_id")
    access_token = payload.get("access_token")

    if not open_id or not access_token:
        msg = payload.get("description") or payload.get("message") or "Unknown error"
        flash(f"TikTok token error: {msg}", "error")
        return redirect(url_for("automation.automation_tiktok"))

    session["tiktok_open_id"]      = open_id
    session["tiktok_access_token"] = access_token
    flash("Zalogowano do TikTok Sandbox pomyślnie!", "success")
    return redirect(url_for("automation.automation_tiktok"))


@tiktok_auth_bp.route("/logout")
def logout():
    """
    Czyszczenie sesji TikTok.
    """
    session.pop("tiktok_open_id", None)
    session.pop("tiktok_access_token", None)
    flash("Wylogowano z TikTok Sandbox.", "success")
    return redirect(url_for("automation.automation_tiktok"))
