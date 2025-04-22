# tiktok_auth.py
import os, requests
from urllib.parse import quote_plus
from flask import Blueprint, redirect, request, flash, url_for, session, jsonify, current_app

tiktok_auth_bp = Blueprint("tiktok_auth", __name__, url_prefix="/tiktok_auth")

TIKTOK_CLIENT_KEY    = os.getenv("TIKTOK_CLIENT_KEY")
TIKTOK_CLIENT_SECRET = os.getenv("TIKTOK_CLIENT_SECRET")
TIKTOK_REDIRECT_URI  = os.getenv("TIKTOK_REDIRECT_URI")

AUTH_URL   = "https://open-sandbox.tiktokapis.com/v2/auth/authorize"
TOKEN_URL  = "https://open-sandbox.tiktokapis.com/v2/oauth/token/"

SCOPES     = "user.info.basic,video.upload,video.list"

@tiktok_auth_bp.route("/login")
def login():
    """Redirect user into TikTok OAuth sandbox login page"""
    current_app.logger.warning("ENV client_key = %r", TIKTOK_CLIENT_KEY)
    url = (
        f"{AUTH_URL}"
        f"?client_key={TIKTOK_CLIENT_KEY}"
        f"&redirect_uri={quote_plus(TIKTOK_REDIRECT_URI)}"
        f"&scope={quote_plus(SCOPES)}"
        f"&response_type=code"
        f"&state=xyz123"
    )
    current_app.logger.debug("authorize_url = %s", url)
    return redirect(url)

@tiktok_auth_bp.route("/callback")
def callback():
    code  = request.args.get("code")
    error = request.args.get("error")
    if error:
        flash(f"TikTok error: {error}", "error")
        return redirect(url_for("automation.automation_tiktok"))
    if not code:
        flash("Missing code from TikTok.", "error")
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
    data = resp.json().get("data", {})
    if resp.status_code != 200 or data.get("error_code"):
        flash(f"TikTok token error: {data.get('description','unknown')}", "error")
        return redirect(url_for("automation.automation_tiktok"))

    session["tiktok_access_token"] = data["access_token"]
    session["tiktok_open_id"]      = data["open_id"]
    flash("Connected to TikTok Sandbox!", "success")
    return redirect(url_for("automation.automation_tiktok"))

@tiktok_auth_bp.route("/test_upload")
def test_upload():
    access_token = session.get("tiktok_access_token")
    if not access_token:
        flash("Login first.", "error")
        return redirect(url_for("automation.automation_tiktok"))

    try:
        with open("test.mp4", "rb") as f:
            resp = requests.post(
                "https://open-sandbox.tiktokapis.com/v2/post/publish/video/upload/",
                files={"video": f},
                headers={"Authorization": f"Bearer {access_token}"},
                timeout=30,
            )
        return jsonify(resp.json())
    except FileNotFoundError:
        return "test.mp4 not found."
