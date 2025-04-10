import os
import requests
from flask import Blueprint, redirect, request, flash, url_for, session, jsonify

# Utwórz nowy blueprint – pamiętaj, by nadać mu unikalną nazwę, np. "tiktok_auth"
tiktok_auth_bp = Blueprint('tiktok_auth', __name__, url_prefix='/tiktok_auth')

# Pobierz dane z zmiennych środowiskowych (ustawione w Heroku jako Config Vars)
TIKTOK_CLIENT_KEY = os.getenv("TIKTOK_CLIENT_KEY", "PLACEHOLDER_KEY")
TIKTOK_CLIENT_SECRET = os.getenv("TIKTOK_CLIENT_SECRET", "PLACEHOLDER_SECRET")
TIKTOK_REDIRECT_URI = os.getenv("TIKTOK_REDIRECT_URI", "https://your-heroku-app.herokuapp.com/tiktok_auth/callback")

@tiktok_auth_bp.route('/login')
def tiktok_login():
    """Przekierowuje użytkownika do logowania przez TikTok (OAuth2 w Sandbox)."""
    scopes = "user.info.basic,video.upload,video.list"
    authorize_url = (
        "https://open-api.tiktok.com/platform/oauth/connect?"
        f"client_key={TIKTOK_CLIENT_KEY}&"
        f"redirect_uri={TIKTOK_REDIRECT_URI}&"
        f"scope={scopes}&"
        "response_type=code&"
        "state=xyz123"
    )

    # Dodaj print tutaj
    print("DEBUG authorize_url:", authorize_url)

    return redirect(authorize_url)


@tiktok_auth_bp.route('/callback')
def tiktok_callback():
    """Odbiera kod autoryzacyjny od TikTok, wymienia go na access_token i zapisuje w session."""
    code = request.args.get("code")
    if not code:
        flash("Brak kodu autoryzacyjnego.", "error")
        return redirect(url_for("automation.automation_tiktok"))
    
    token_url = "https://open-api.tiktok.com/oauth/access_token"
    data = {
        "client_key": TIKTOK_CLIENT_KEY,
        "client_secret": TIKTOK_CLIENT_SECRET,
        "code": code,
        "grant_type": "authorization_code",
        "redirect_uri": TIKTOK_REDIRECT_URI
    }
    response = requests.post(token_url, data=data)
    token_json = response.json()
    
    error_code = token_json.get("data", {}).get("error_code")
    if error_code and error_code != 0:
        flash(f"Błąd autoryzacji TikTok: {token_json}", "error")
        return redirect(url_for("automation.automation_tiktok"))
    
    access_token = token_json["data"].get("access_token")
    open_id = token_json["data"].get("open_id")
    session["tiktok_access_token"] = access_token
    session["tiktok_open_id"] = open_id
    
    flash("Pomyślnie połączono z TikTok (Sandbox).", "success")
    return redirect(url_for("automation.automation_tiktok"))

@tiktok_auth_bp.route('/test_upload')
def tiktok_test_upload():
    """
    Przykładowy endpoint do testowego wysłania wideo.
    Upewnij się, że plik "test.mp4" jest dostępny w katalogu aplikacji.
    """
    access_token = session.get("tiktok_access_token")
    if not access_token:
        flash("Najpierw zaloguj się przez TikTok.", "error")
        return redirect(url_for("automation.automation_tiktok"))
    
    upload_url = "https://open-api.tiktok.com/video/upload/"
    video_file_path = "test.mp4"  # Upewnij się, że taki plik istnieje!
    
    try:
        with open(video_file_path, "rb") as f:
            files = {"video": f}
            headers = {"Authorization": f"Bearer {access_token}"}
            resp = requests.post(upload_url, files=files, headers=headers)
        return jsonify(resp.json())
    except FileNotFoundError:
        return "Brak pliku test.mp4. Upewnij się, że plik jest dostępny."
