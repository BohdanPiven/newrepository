import os
import requests
from flask import Blueprint, render_template_string, url_for, request, flash, redirect, session, jsonify
from datetime import datetime
from app import db  # import instancji SQLAlchemy z Twojego głównego pliku (app.py)
from automation_models import ScheduledPost  # Twój model zdefiniowany w automation_models.py

# Pobieramy dane z config vars Heroku (lub z .env na lokalnym)
TIKTOK_CLIENT_KEY = os.getenv("TIKTOK_CLIENT_KEY", "PLACEHOLDER_KEY")
TIKTOK_CLIENT_SECRET = os.getenv("TIKTOK_CLIENT_SECRET", "PLACEHOLDER_SECRET")
TIKTOK_REDIRECT_URI = os.getenv("TIKTOK_REDIRECT_URI", "https://twojaapka.herokuapp.com/automation/tiktok/callback")

automation_bp = Blueprint('automation', __name__, url_prefix='/automation')

@automation_bp.route('/', endpoint='automation_home')
def automation_home():
    """
    Strona główna panelu automatyzacji.
    """
    home_template = '''
    <!DOCTYPE html>
    <html lang="pl">
    <head>
        <meta charset="UTF-8">
        <title>Automation - Główna</title>
        ...
    </head>
    <body>
        <div class="container">
            <a href="{{ url_for('index') }}" class="back-button">back</a>
            <h1>Panel Automatyzacji</h1>
            <p>Wybierz platformę, którą chcesz konfigurować lub automatyzować:</p>
            <div class="platform-list">
                <a href="{{ url_for('automation.automation_tiktok') }}">TikTok</a>
                <a href="{{ url_for('automation.automation_facebook') }}">Facebook</a>
            </div>
        </div>
    </body>
    </html>
    '''
    return render_template_string(home_template)

# --- Poniżej Twoje istniejące endpointy do planu / timeline / itd. ---
# (automation_tiktok, automation_tiktok_plan, edit_scheduled_post, delete_scheduled_post, 
#  automation_tiktok_timeline, automation_tiktok_rodzaje, automation_tiktok_scenariusze, 
#  automation_facebook)
# ... niezmienione ...

# -- DODAJEMY NOWE ROUTES DLA OAUTH2 Z TIKTOK --

@automation_bp.route('/tiktok/login')
def tiktok_login():
    """
    Endpoint: przekierowanie użytkownika do logowania przez TikTok.
    W trybie Sandbox musisz mieć scope'y takie same,
    jakie wybrałeś w panelu (np. user.info.basic, video.upload, video.list).
    """
    scopes = "user.info.basic,video.upload,video.list"
    
    # Budujemy URL autoryzacji do TikTok
    authorize_url = (
        "https://open-api.tiktok.com/platform/oauth/connect?"
        f"client_key={TIKTOK_CLIENT_KEY}&"
        f"redirect_uri={TIKTOK_REDIRECT_URI}&"
        f"scope={scopes}&"
        "response_type=code&"
        "state=xyz123"  # cokolwiek, np. do ochrony CSRF
    )
    return redirect(authorize_url)

@automation_bp.route('/tiktok/callback')
def tiktok_callback():
    """
    Endpoint: TikTok przekierowuje tu po udanym logowaniu i wyrażeniu zgody.
    Pobieramy 'code' z query params, wymieniamy na 'access_token', zapisujemy do session.
    """
    code = request.args.get("code")
    if not code:
        flash("Brak parametru 'code' w odpowiedzi z TikTok.", "error")
        return redirect(url_for('automation.automation_tiktok'))

    # Wywołanie endpointu: wymiana code -> access_token
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
    
    # Sprawdź, czy jest error
    error_code = token_json.get("data", {}).get("error_code")
    if error_code and error_code != 0:
        flash(f"Błąd w autoryzacji TikTok: {token_json}", "error")
        return redirect(url_for('automation.automation_tiktok'))

    # Wyciągamy kluczowe dane
    access_token = token_json["data"].get("access_token")
    open_id = token_json["data"].get("open_id")

    # Przechowujemy w session (lub w bazie) - zależnie od Twojej logiki
    session["tiktok_access_token"] = access_token
    session["tiktok_open_id"] = open_id

    flash("Pomyślnie połączono z TikTok (Sandbox).", "success")
    return redirect(url_for('automation.automation_tiktok'))

@automation_bp.route('/tiktok/test_upload')
def tiktok_test_upload():
    """
    PRZYKŁADOWY endpoint do testu wrzucenia wideo w trybie Sandbox (Content Posting API).
    - Upewnij się, że w panelu TikTok masz włączone "video.upload" w Sandbox.
    - W Heroku będzie problem z zapisem plików na dysku, więc 
      lepiej w praktyce używać plików z zewnętrznego storage.
    """
    access_token = session.get("tiktok_access_token")
    if not access_token:
        flash("Brak access_token. Najpierw zaloguj się przez TikTok!", "error")
        return redirect(url_for('automation.automation_tiktok'))
    
    # Teoretycznie: wysyłamy plik MP4 do TikTok. W Sandbox to zwykle zapisuje się w Drafts.
    upload_url = "https://open-api.tiktok.com/video/upload/"

    # Tu powinieneś mieć ścieżkę do jakiegoś małego filmiku test.mp4
    # Na Heroku pliki są ephemeral, więc to  bardziej do demonstracji. 
    # Możesz też pobrać plik z zew. URL i wysłać w memory streamie.
    video_file_path = "test.mp4"  # PRZYKŁAD, w praktyce musisz go dołączyć w repo lub pobierać z zewnętrznego źródła

    try:
        with open(video_file_path, "rb") as f:
            files = {"video": f}
            headers = {"Authorization": f"Bearer {access_token}"}
            resp = requests.post(upload_url, files=files, headers=headers)
        data = resp.json()
        return jsonify(data)
    except FileNotFoundError:
        return "Brak pliku test.mp4. Wrzuć go do repo lub użyj zewnętrznego storage."

