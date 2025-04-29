# tiktok_auth.py
import os
import requests
from urllib.parse import quote_plus
from flask import Blueprint, redirect, request, flash, url_for, session, jsonify, current_app

# Blueprint initialization
# Ensure no leading indentation before this line

tiktok_auth_bp = Blueprint(
    "tiktok_auth",
    __name__,
    url_prefix="/tiktok_auth"
)

# Environment variables (set these in Heroku or your hosting environment)
TIKTOK_CLIENT_KEY    = os.getenv("TIKTOK_CLIENT_KEY")
TIKTOK_CLIENT_SECRET = os.getenv("TIKTOK_CLIENT_SECRET")
TIKTOK_REDIRECT_URI  = os.getenv("TIKTOK_REDIRECT_URI")

# TikTok OAuth endpoints for Sandbox (use correct open.tiktokapis.com domain)
AUTH_URL         = "https://www.tiktok.com/v2/auth/authorize"
TOKEN_URL        = "https://open.tiktokapis.com/v2/oauth/token/"
USER_INFO_URL    = "https://open.tiktokapis.com/v2/user/info/"
UPLOAD_VIDEO_URL = "https://open.tiktokapis.com/v2/post/publish/video/upload/"

# Requested scopes (comma-separated)
SCOPES = "user.info.basic"

@tiktok_auth_bp.route("/login")
def login():
    """Redirect user into TikTok OAuth sandbox login page"""
    current_app.logger.debug("TikTok Login: client_key=%r", TIKTOK_CLIENT_KEY)
    # Build authorization URL parameters
    params = {
        "client_key": TIKTOK_CLIENT_KEY,
        "redirect_uri": TIKTOK_REDIRECT_URI,
        "scope": SCOPES,
        "response_type": "code",
        "state": "xyz123",
    }
    # Build query string
    query = "&".join(f"{key}={quote_plus(value)}" for key, value in params.items())
    authorize_url = f"{AUTH_URL}?{query}"
    current_app.logger.debug("Authorize URL: %s", authorize_url)
    return redirect(authorize_url)

@tiktok_auth_bp.route("/callback")
def callback():
    """Handle TikTok OAuth callback, exchange code for access token and open_id"""
    error = request.args.get("error")
    if error:
        flash(f"TikTok error: {error}", "error")
        return redirect(url_for("automation.automation_tiktok"))

    code = request.args.get("code")
    if not code:
        flash("Missing code from TikTok.", "error")
        return redirect(url_for("automation.automation_tiktok"))

    current_app.logger.debug("Received code: %s", code)
    # Exchange code for access token
    try:
        resp = requests.post(
            TOKEN_URL,
            data={
                "client_key": TIKTOK_CLIENT_KEY,
                "client_secret": TIKTOK_CLIENT_SECRET,
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": TIKTOK_REDIRECT_URI,
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
    current_app.logger.warning("TikTok token response: %r", result)
    data = result.get("data", {})
    open_id = data.get("open_id")
    access_token = data.get("access_token")

    if not open_id or not access_token:
        desc = data.get("description") or result.get("message") or "Unknown error"
        flash(f"TikTok token error: {desc}", "error")
        return redirect(url_for("automation.automation_tiktok"))

    # Save to session
    session["tiktok_access_token"] = access_token
    session["tiktok_open_id"]      = open_id
    flash("Connected to TikTok Sandbox!", "success")
    return redirect(url_for("automation.automation_tiktok"))

@tiktok_auth_bp.route("/test_upload")
def test_upload():
    """Upload test video to TikTok sandbox using stored access token"""
    access_token = session.get("tiktok_access_token")
    if not access_token:
        flash("Login first.", "error")
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
        flash("test.mp4 not found.", "error")
        return redirect(url_for("automation.automation_tiktok"))
    except requests.RequestException as e:
        current_app.logger.error("Upload failed: %s", e)
        flash("Video upload failed.", "error")
        return redirect(url_for("automation.automation_tiktok"))
