# tiktok_auth.py
import os
import requests
from urllib.parse import quote_plus
from flask import (
    Blueprint, redirect, request, flash,
    url_for, session, jsonify, current_app
)

tiktok_auth_bp = Blueprint(
    "tiktok_auth",
    __name__,
    url_prefix="/tiktok_auth"
)

# Środowiskowe
TIKTOK_CLIENT_KEY    = os.getenv("TIKTOK_CLIENT_KEY")
TIKTOK_CLIENT_SECRET = os.getenv("TIKTOK_CLIENT_SECRET")
TIKTOK_REDIRECT_URI  = os.getenv("TIKTOK_REDIRECT_URI")

# OAuth endpoints
AUTH_URL         = "https://www.tiktok.com/v2/auth/authorize"
TOKEN_URL        = "https://open.tiktokapis.com/v2/oauth/token/"
USER_INFO_URL    = "https://open.tiktokapis.com/v2/user/info/"
UPLOAD_VIDEO_URL = "https://open.tiktokapis.com/v2/post/publish/video/upload/"

SCOPES = "user.info.basic"


@tiktok_auth_bp.route("/login")
def login():
    """Przekierowanie do TikTok OAuth (Sandbox)"""
    params = {
        "client_key":    TIKTOK_CLIENT_KEY,
        "redirect_uri":  TIKTOK_REDIRECT_URI,
        "scope":         SCOPES,
        "response_type": "code",
        "state":         "xyz123",
    }
    query = "&".join(f"{k}={quote_plus(v)}" for k, v in params.items())
    authorize_url = f"{AUTH_URL}?{query}"
    current_app.logger.debug("Authorize URL: %s", authorize_url)
    return redirect(authorize_url)


@tiktok_auth_bp.route("/callback")
def callback():
    """Obsługa callback — wymiana code na token + open_id"""
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
    current_app.logger.warning("🎯 TikTok token response JSON: %r", result)

    data = result.get("data", {})
    open_id = data.get("open_id")
    access_token = data.get("access_token")

    if not open_id or not access_token:
        desc = data.get("description") or result.get("message") or "Unknown error"
        flash(f"TikTok token error: {desc}", "error")
        return redirect(url_for("automation.automation_tiktok"))

    session["tiktok_access_token"] = access_token
    session["tiktok_open_id"]      = open_id
    flash("Zalogowano pomyślnie.", "success")
    return redirect(url_for("automation.automation_tiktok"))


@tiktok_auth_bp.route("/logout")
def logout():
    """Wylogowanie — czyści sesję TikTok"""
    session.pop("tiktok_access_token", None)
    session.pop("tiktok_open_id", None)
    flash("Wylogowano z TikTok Sandbox.", "success")
    return redirect(url_for("automation.automation_tiktok"))


@tiktok_auth_bp.route("/test_upload")
def test_upload():
    """Testowe upload video"""
    access_token = session.get("tiktok_access_token")
    if not access_token:
        flash("Musisz się najpierw zalogować.", "error")
        return redirect(url_for("automation.automation_tiktok"))

    try:
        with open("test.mp4", "rb") as f:
            resp = requests.post(
                UPLOAD_VIDEO_URL,
                files={"video": f},
                headers={"Authorization": f"Bearer {access_token}"},
                timeout=30,
            )
            resp.raise_for_status()
        return jsonify(resp.json())
    except FileNotFoundError:
        flash("Plik test.mp4 nie został znaleziony.", "error")
    except requests.RequestException as e:
        current_app.logger.error("Upload failed: %s", e)
        flash("Wysyłka wideo nie powiodła się.", "error")

    return redirect(url_for("automation.automation_tiktok"))
