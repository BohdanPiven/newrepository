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

TIKTOK_CLIENT_KEY    = os.getenv("TIKTOK_CLIENT_KEY")
TIKTOK_CLIENT_SECRET = os.getenv("TIKTOK_CLIENT_SECRET")
TIKTOK_REDIRECT_URI  = os.getenv("TIKTOK_REDIRECT_URI")

# **POPRAWIONE** endpointy:
AUTH_URL              = "https://open.tiktokapis.com/v2/oauth/authorize"
TOKEN_URL             = "https://open.tiktokapis.com/v2/oauth/token/"
USER_INFO_URL         = "https://open.tiktokapis.com/v2/user/info/"
VIDEO_INIT_UPLOAD_URL = "https://open.tiktokapis.com/v2/post/publish/inbox/video/init/"

# na razie tylko te dwa, które masz w panelu
SCOPES = "user.info.basic video.upload"


@tiktok_auth_bp.route("/login")
def login():
    params = {
        "client_key":    TIKTOK_CLIENT_KEY,
        "redirect_uri":  TIKTOK_REDIRECT_URI,
        "scope":         SCOPES,
        "response_type": "code",
        "state":         "xyz123",
    }
    qs = "&".join(f"{k}={quote_plus(v)}" for k, v in params.items())
    return redirect(f"{AUTH_URL}?{qs}")


@tiktok_auth_bp.route("/callback")
def callback():
    if err := request.args.get("error"):
        flash(f"TikTok error: {err}", "error")
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

    data = resp.json().get("data", resp.json())
    open_id      = data.get("open_id")
    access_token = data.get("access_token")
    if not open_id or not access_token:
        desc = data.get("description") or data.get("message") or "Unknown error"
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
