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

# ————————————
# Konfiguracja z Heroku Config Vars
# ————————————
TIKTOK_CLIENT_KEY    = os.getenv("TIKTOK_CLIENT_KEY")
TIKTOK_CLIENT_SECRET = os.getenv("TIKTOK_CLIENT_SECRET")
TIKTOK_REDIRECT_URI  = os.getenv("TIKTOK_REDIRECT_URI")

# ————————————
# Sandbox OAuth Endpoints
# ————————————
AUTH_URL         = "https://open.tiktokapis.com/v2/auth/authorize/"
TOKEN_URL        = "https://open.tiktokapis.com/v2/oauth/token/"
USER_INFO_URL    = "https://open.tiktokapis.com/v2/user/info/"
VIDEO_INIT_URL   = "https://open.tiktokapis.com/v2/post/publish/video/init/"
UPLOAD_VIDEO_URL = "https://open.tiktokapis.com/v2/post/publish/video/upload/"

# ————————————
# Scope’y wymagane przez sandbox:
#  • user.info.basic – dostęp do open_id + basic profile
#  • video.upload     – inicjacja uploadu
#  • video.list       – (opcjonalnie) pobieranie listy wgranych filmów
# ————————————
SCOPES = "user.info.basic,video.upload,video.list"


@tiktok_auth_bp.route("/login")
def login():
    """
    Kieruje do TikTok OAuth Sandbox z odpowiednimi parametrami.
    """
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
    """
    Odbiera 'code', wymienia na access_token + open_id,
    zapisuje je w sesji lub pokazuje błąd.
    """
    if err := request.args.get("error"):
        flash(f"TikTok error: {err}", "error")
        return redirect(url_for("automation.automation_tiktok"))

    code = request.args.get("code")
    if not code:
        flash("Brak kodu autoryzacyjnego od TikToka.", "error")
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
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept":       "application/json",
            },
            timeout=10
        )
        resp.raise_for_status()
    except requests.RequestException as e:
        current_app.logger.error("Token exchange failed: %s", e)
        flash("Nie udało się wymienić kodu na token.", "error")
        return redirect(url_for("automation.automation_tiktok"))

    payload = resp.json()
    data = payload.get("data", payload)
    open_id      = data.get("open_id")
    access_token = data.get("access_token")

    if not (open_id and access_token):
        msg = data.get("description") or data.get("message") or "Nieznany błąd"
        flash(f"Błąd przy pobieraniu tokena: {msg}", "error")
        return redirect(url_for("automation.automation_tiktok"))

    session["tiktok_open_id"]      = open_id
    session["tiktok_access_token"] = access_token
    flash("Zalogowano pomyślnie z pełnymi uprawnieniami.", "success")
    return redirect(url_for("automation.automation_tiktok"))


@tiktok_auth_bp.route("/logout")
def logout():
    """
    Wylogowuje użytkownika z TikTok Sandbox (czyści sesję).
    """
    session.pop("tiktok_open_id", None)
    session.pop("tiktok_access_token", None)
    flash("Wylogowano z TikTok Sandbox.", "success")
    return redirect(url_for("automation.automation_tiktok"))
