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
    current_app
)

tiktok_auth_bp = Blueprint(
    "tiktok_auth",
    __name__,
    url_prefix="/tiktok_auth"
)

# -- Środowiskowe zmienne (Heroku Config Vars) --
TIKTOK_CLIENT_KEY    = os.getenv("TIKTOK_CLIENT_KEY")
TIKTOK_CLIENT_SECRET = os.getenv("TIKTOK_CLIENT_SECRET")
TIKTOK_REDIRECT_URI  = os.getenv("TIKTOK_REDIRECT_URI")

# -- TikTok OAuth Endpoints (Sandbox uses open.tiktokapis.com) --
AUTH_URL                = "https://open.tiktokapis.com/v2/auth/authorize/"
TOKEN_URL               = "https://open.tiktokapis.com/v2/oauth/token/"
USER_INFO_URL           = "https://open.tiktokapis.com/v2/user/info/"
VIDEO_INIT_UPLOAD_URL   = "https://open.tiktokapis.com/v2/post/publish/inbox/video/init/"

# -- Scope’y, których potrzeba --
# - user.info.basic  — żeby pobrać open_id i access_token
# - video.upload      — żeby zainicjalizować upload filmu
# - (opcjonalnie) video.list — żeby później listować wrzucone filmy
SCOPES = "user.info.basic video.upload video.list"


@tiktok_auth_bp.route("/login")
def login():
    params = {
        "client_key":    TIKTOK_CLIENT_KEY,
        "redirect_uri":  TIKTOK_REDIRECT_URI,
        "scope":         SCOPES,
        "response_type": "code",
        "state":         "xyz123",
    }
    # wygeneruj query-string
    query = "&".join(f"{k}={quote_plus(v)}" for k, v in params.items())
    return redirect(f"{AUTH_URL}?{query}")


@tiktok_auth_bp.route("/callback")
def callback():
    error = request.args.get("error")
    if error:
        flash(f"TikTok error: {error}", "error")
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
    current_app.logger.debug("Token response JSON: %r", result)

    open_id      = result.get("open_id")      or result.get("data", {}).get("open_id")
    access_token = result.get("access_token") or result.get("data", {}).get("access_token")

    if not open_id or not access_token:
        desc = result.get("description") or result.get("message") or "Unknown error"
        flash(f"TikTok token error: {desc}", "error")
        return redirect(url_for("automation.automation_tiktok"))

    session["tiktok_open_id"]      = open_id
    session["tiktok_access_token"] = access_token
    flash("Zalogowano pomyślnie.", "success")
    return redirect(url_for("automation.automation_tiktok"))


@tiktok_auth_bp.route("/logout")
def logout():
    session.pop("tiktok_open_id", None)
    session.pop("tiktok_access_token", None)
    flash("Wylogowano z TikTok Sandbox.", "success")
    return redirect(url_for("automation.automation_tiktok"))
