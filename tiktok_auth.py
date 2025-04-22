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
    current_app,   # <-- używamy do logowania
)

# ───────────────────────────────────────────────────────────────────────────────
# Blueprint
# ───────────────────────────────────────────────────────────────────────────────
tiktok_auth_bp = Blueprint("tiktok_auth", __name__, url_prefix="/tiktok_auth")

# ───────────────────────────────────────────────────────────────────────────────
# Zmienne środowiskowe / Heroku Config Vars
# ───────────────────────────────────────────────────────────────────────────────
TIKTOK_CLIENT_KEY    = os.getenv("TIKTOK_CLIENT_KEY",    "PLACEHOLDER_KEY")
TIKTOK_CLIENT_SECRET = os.getenv("TIKTOK_CLIENT_SECRET", "PLACEHOLDER_SECRET")
TIKTOK_REDIRECT_URI  = os.getenv(
    "TIKTOK_REDIRECT_URI",
    "https://your-heroku-app.herokuapp.com/tiktok_auth/callback"
)

# ───────────────────────────────────────────────────────────────────────────────
# Sandbox v2 endpointy
# ───────────────────────────────────────────────────────────────────────────────
TIKTOK_AUTH_URL  = "https://www.tiktok.com/v2/auth/authorize"
TIKTOK_TOKEN_URL = "https://open.tiktokapis.com/v2/oauth/token/"

# ───────────────────────────────────────────────────────────────────────────────
# /login  → przekierowanie do logowania TikToka
# ───────────────────────────────────────────────────────────────────────────────

SCOPES = "user.info.basic video.upload video.list"

@tiktok_auth_bp.route("/login")
def tiktok_login():
    redirect_enc = quote_plus(TIKTOK_REDIRECT_URI, safe="")
    scopes_enc   = quote_plus(SCOPES,              safe="")  # ❷ kodujemy

    authorize_url = (
        f"{TIKTOK_AUTH_URL}"
        f"?client_key={TIKTOK_CLIENT_KEY}"
        f"&redirect_uri={redirect_enc}"
        f"&scope={scopes_enc}"
        f"&response_type=code"
        f"&state=xyz123"
    )

    current_app.logger.debug("authorize_url: %s", authorize_url)
    return redirect(authorize_url)

# ───────────────────────────────────────────────────────────────────────────────
# /callback  → wymiana code → access_token
# ───────────────────────────────────────────────────────────────────────────────
@tiktok_auth_bp.route("/callback")
def tiktok_callback():
    logger = current_app.logger

    code  = request.args.get("code")
    error = request.args.get("error")

    logger.debug("[TikTok CB] code=%s  error=%s", code, error)

    if error:
        flash(f"TikTok zwrócił błąd: {error}", "error")
        return redirect(url_for("automation.automation_tiktok"))

    if not code:
        flash("TikTok nie odesłał kodu autoryzacyjnego.", "error")
        return redirect(url_for("automation.automation_tiktok"))

    payload = {
        "client_key":     TIKTOK_CLIENT_KEY,
        "client_secret":  TIKTOK_CLIENT_SECRET,
        "code":           code,
        "grant_type":     "authorization_code",
        "redirect_uri":   TIKTOK_REDIRECT_URI,
    }

    try:
        resp = requests.post(
            TIKTOK_TOKEN_URL,
            data=payload,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=10,
        )
    except Exception:
        logger.exception("TikTok token‑request failed")
        flash("Nie udało się połączyć z TikTok (token).", "error")
        return redirect(url_for("automation.automation_tiktok"))

    logger.debug("[TikTok CB] token_resp %s  %s",
                 resp.status_code, resp.text[:400])

    if resp.status_code != 200:
        flash("Błąd po stronie TikToka (token).", "error")
        return redirect(url_for("automation.automation_tiktok"))

    data = resp.json().get("data", {})
    if data.get("error_code", 0) != 0:
        flash(f"TikTok zwrócił błąd: {data.get('description','unknown')}", "error")
        return redirect(url_for("automation.automation_tiktok"))

    # — sukces —
    session["tiktok_access_token"] = data.get("access_token")
    session["tiktok_open_id"]      = data.get("open_id")

    flash("Połączono z TikTok (Sandbox).", "success")
    return redirect(url_for("automation.automation_tiktok"))

# ───────────────────────────────────────────────────────────────────────────────
# /test_upload  – upload wideo (push_by_file) do Content Posting API
# ───────────────────────────────────────────────────────────────────────────────
@tiktok_auth_bp.route("/test_upload")
def tiktok_test_upload():
    """
    Przykładowy endpoint do testowego wysłania wideo (działa po autoryzacji).
    """
    access_token = session.get("tiktok_access_token")
    if not access_token:
        flash("Najpierw zaloguj się przez TikTok.", "error")
        return redirect(url_for("automation.automation_tiktok"))

    upload_url       = "https://open-sandbox.tiktokapis.com/v2/post/publish/video/upload/"
    video_file_path  = "test.mp4"      # upewnij się, że plik istnieje w repo

    try:
        with open(video_file_path, "rb") as f:
            files   = {"video": f}
            headers = {"Authorization": f"Bearer {access_token}"}
            resp    = requests.post(upload_url, files=files,
                                    headers=headers, timeout=30)
        return jsonify(resp.json())
    except FileNotFoundError:
        return "Brak pliku test.mp4 w katalogu aplikacji."
