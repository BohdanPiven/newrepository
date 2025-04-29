import os
import requests
from flask import (
    Blueprint,
    render_template,
    request,
    redirect,
    url_for,
    flash,
    session,
    current_app
)
from urllib.parse import quote_plus

video_bp = Blueprint("tiktok_video", __name__, url_prefix="/tiktok_video")

# Endpoints
AUTH_URL              = "https://open.tiktokapis.com/v2/auth/authorize"
TOKEN_URL             = "https://open.tiktokapis.com/v2/oauth/token/"
INIT_UPLOAD_URL       = "https://open.tiktokapis.com/v2/post/publish/video/init/"
PUBLISH_VIDEO_URL     = "https://open.tiktokapis.com/v2/post/publish/"

# Scopes konieczne do uploadu
SCOPES_VIDEO = "user.info.basic video.upload"

# Te same env vars co w tiktok_auth.py
CLIENT_KEY    = os.getenv("TIKTOK_CLIENT_KEY")
CLIENT_SECRET = os.getenv("TIKTOK_CLIENT_SECRET")
REDIRECT_URI  = os.getenv("TIKTOK_REDIRECT_URI")


@video_bp.route("/login")
def login_video():
    """Przekierowanie do TikToka z video.upload."""
    params = {
        "client_key":    CLIENT_KEY,
        "redirect_uri":  REDIRECT_URI,
        "scope":         SCOPES_VIDEO,
        "response_type": "code",
        "state":         "upload123",
    }
    qs = "&".join(f"{k}={quote_plus(v)}" for k, v in params.items())
    return redirect(f"{AUTH_URL}?{qs}")


@video_bp.route("/upload_form")
def upload_form():
    """
    Formularz przesyłania pliku.
    Wymaga, żebyś już był(-a) zalogowany(a) z video.upload – 
    tzn. sesja musi mieć tiktok_access_token.
    """
    if "tiktok_access_token" not in session:
        flash("Najpierw musisz się zalogować z prawami video.upload", "error")
        return redirect(url_for("tiktok_video.login_video"))
    return render_template("upload_video.html")


@video_bp.route("/upload", methods=["POST"])
def do_upload():
    """
    1) Wywołanie INIT,
    2) PUT na upload_url,
    3) POST publish.
    """
    token   = session.get("tiktok_access_token")
    open_id = session.get("tiktok_open_id")
    if not token or not open_id:
        flash("Brak tokenu w sesji – zaloguj się ponownie.", "error")
        return redirect(url_for("tiktok_video.login_video"))

    video_file = request.files.get("video")
    title      = request.form.get("title", "")
    if not video_file:
        flash("Wybierz plik .mp4 lub .mov", "error")
        return redirect(url_for("tiktok_video.upload_form"))

    # 1) INIT
    init_resp = requests.post(
        INIT_UPLOAD_URL,
        headers={"Access-Token": token},
        json={
            "upload_type": "video",
            "video_type":  "NORMAL",
            "file_name":   video_file.filename
        },
        timeout=10
    )
    if init_resp.status_code != 200:
        current_app.logger.error("INIT failed: %s", init_resp.text)
        flash("Inicjalizacja uploadu nie powiodła się.", "error")
        return redirect(url_for("tiktok_video.upload_form"))

    init_data = init_resp.json().get("data", {})
    upload_url = init_data.get("upload_url")
    video_id   = init_data.get("video_id")
    if not upload_url or not video_id:
        flash("INIT zwróciło niepełne dane.", "error")
        return redirect(url_for("tiktok_video.upload_form"))

    # 2) Przesłanie pliku
    put_resp = requests.put(upload_url, data=video_file.read(), timeout=30)
    if put_resp.status_code not in (200, 201):
        current_app.logger.error("PUT upload failed: %s", put_resp.text)
        flash("Przesyłanie pliku nie powiodło się.", "error")
        return redirect(url_for("tiktok_video.upload_form"))

    # 3) Publikacja
    pub_resp = requests.post(
        PUBLISH_VIDEO_URL,
        headers={"Access-Token": token},
        json={"video_id": video_id, "text": title},
        timeout=10
    )
    if pub_resp.status_code != 200:
        current_app.logger.error("Publish failed: %s", pub_resp.text)
        flash("Publikacja nie powiodła się.", "error")
        return redirect(url_for("tiktok_video.upload_form"))

    flash("Film wysłany do Sandboxa!", "success")
    return redirect(url_for("automation.automation_tiktok"))
