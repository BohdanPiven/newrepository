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

# -- Środowiskowe zmienne (Heroku: Config Vars) --
TIKTOK_CLIENT_KEY    = os.getenv("TIKTOK_CLIENT_KEY")
TIKTOK_CLIENT_SECRET = os.getenv("TIKTOK_CLIENT_SECRET")
TIKTOK_REDIRECT_URI  = os.getenv("TIKTOK_REDIRECT_URI")

# -- TikTok OAuth Sandbox Endpoints --
AUTH_URL         = "https://open.tiktokapis.com/v2/auth/authorize/"
TOKEN_URL        = "https://open.tiktokapis.com/v2/oauth/token/"
USER_INFO_URL    = "https://open.tiktokapis.com/v2/user/info/"
VIDEO_INIT_URL   = "https://open.tiktokapis.com/v2/post/publish/video/init/"
UPLOAD_VIDEO_URL = "https://open.tiktokapis.com/v2/post/publish/video/upload/"

# Potrzebne scope’y:
#  - user.info.basic  — do pobrania open_id i access_token
#  - video.upload      — do inicjacji uploadu pliku
#  - video.list        — (opcjonalnie) do listowania wstawionych filmów
SCOPES = "user.info.basic video.upload video.list"


@tiktok_auth_bp.route("/login")
def login():
    """
    Przekierowuje użytkownika do TikTok OAuth Sandbox
    z odpowiednimi parametrami i scope’ami.
    """
    params = {
        "client_key":    TIKTOK_CLIENT_KEY,
        "redirect_uri":  TIKTOK_REDIRECT_URI,
        "scope":         SCOPES,
        "response_type": "code",
        "state":         "xyz123",
    }
    # składamy query-string
    query = "&".join(f"{k}={quote_plus(v)}" for k, v in params.items())
    return redirect(f"{AUTH_URL}?{query}")


@tiktok_auth_bp.route("/callback")
def callback():
    """
    Obsługa callbacku OAuth:
     1) odbiór parametru 'code'
     2) wymiana na access_token + open_id
     3) zapis w sesji Flask
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
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=10,
        )
        resp.raise_for_status()
    except requests.RequestException as e:
        current_app.logger.error("Token exchange failed: %s", e)
        flash("Nie udało się wymienić kodu na token.", "error")
        return redirect(url_for("automation.automation_tiktok"))

    data = resp.json().get("data", resp.json())
    open_id      = data.get("open_id")
    access_token = data.get("access_token")

    if not open_id or not access_token:
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
    Wylogowanie – czyszczenie sesji OAuth.
    """
    session.pop("tiktok_open_id", None)
    session.pop("tiktok_access_token", None)
    flash("Wylogowano z TikTok Sandbox.", "success")
    return redirect(url_for("automation.automation_tiktok"))
