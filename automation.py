# automation.py
import requests
from datetime import datetime
from os import getenv
from flask import (
    Blueprint, render_template_string, url_for, request,
    flash, redirect, session, jsonify, get_flashed_messages, current_app
)

from app import db
from automation_models import ScheduledPost
from selenium_facebook_post import publish_post_to_facebook

TIKTOK_CLIENT_KEY = getenv("TIKTOK_CLIENT_KEY")

automation_bp = Blueprint("automation", __name__, url_prefix="/automation")

# ─────────────────────────  PANEL HOME  ────────────────────────────
@automation_bp.route("/", endpoint="automation_home")
def automation_home():
    tpl = """<!DOCTYPE html><html lang="pl"><head><meta charset="UTF-8">
    <title>Panel Automatyzacji</title><style>
      *{margin:0;padding:0;box-sizing:border-box;}body{font-family:Arial,sans-serif;background:#f2f2f2;}
      .container{max-width:600px;margin:20px auto;background:#fff;padding:20px;box-shadow:0 4px 8px rgba(0,0,0,0.1);}
      .platform-list a{display:block;margin:6px 0;padding:8px 12px;background:#1f8ef1;color:#fff;text-decoration:none;border-radius:4px;}
      .platform-list a:hover{background:#0a6db9;}
    </style></head><body>
      <div class="container">
        <h1>Panel Automatyzacji</h1>
        <div class="platform-list">
          <a href="{{ url_for('automation.automation_tiktok') }}">TikTok</a>
          <a href="{{ url_for('automation.automation_facebook') }}">Facebook</a>
        </div>
      </div></body></html>"""
    return render_template_string(tpl)

# ─────────────────────  TIKTOK GŁÓWNA  ────────────────────────────
@automation_bp.route("/tiktok", endpoint="automation_tiktok")
def automation_tiktok():
    tpl = """<!DOCTYPE html><html lang="pl"><head><meta charset="UTF-8">
    <title>Automatyzacja TikTok</title>… (HTML bez zmian) …"""
    return render_template_string(tpl)

# ──────────────────────  PLAN TREŚCI  ──────────────────────────────
@automation_bp.route("/tiktok/plan", methods=["GET", "POST"], endpoint="automation_tiktok_plan")
def automation_tiktok_plan():
    … (bez zmian) …

# ───────────────────  FULLCALENDAR EVENTS  ──────────────────────────
@automation_bp.route("/tiktok/events", endpoint="automation_tiktok_events")
def tiktok_events():
    … (bez zmian) …

# ───────────────────  TIMELINE (FULLCALENDAR)  ─────────────────────
@automation_bp.route("/tiktok/timeline", endpoint="automation_tiktok_timeline")
def automation_tiktok_timeline():
    … (bez zmian) …

# ──────────  ROUTES STATYCZNE  ──────────────────────────────────────
@automation_bp.route("/tiktok/rodzaje", endpoint="automation_tiktok_rodzaje")
def automation_tiktok_rodzaje():
    return render_template_string("…")

@automation_bp.route("/tiktok/scenariusze", endpoint="automation_tiktok_scenariusze")
def automation_tiktok_scenariusze():
    return render_template_string("…")

# ───────────────────  UPLOAD WIDEO  ────────────────────────────────
@automation_bp.route("/tiktok/video", methods=["GET", "POST"], endpoint="automation_tiktok_video")
def automation_tiktok_video():
    if "tiktok_open_id" not in session:
        flash("Musisz się połączyć z TikTok.", "error")
        return redirect(url_for("automation.automation_tiktok"))

    if request.method == "GET":
        return render_template_string("""<!DOCTYPE html><html lang="pl"><head>
            <meta charset="UTF-8"><title>Upload wideo TikTok</title></head><body
            style="font-family:Arial,sans-serif;padding:20px">
              <h1>Upload wideo – TikTok Sandbox</h1>
              <form method="post" enctype="multipart/form-data">
                <input type="file" name="video_file" accept="video/*" required><br><br>
                <button type="submit">Wyślij</button>
              </form>
              <p><a href="{{ url_for('automation.automation_tiktok') }}">← Powrót</a></p>
            </body></html>""")

    f = request.files.get("video_file")
    if not f:
        flash("Nie wybrano pliku.", "error")
        return redirect(url_for("automation.automation_tiktok_video"))

    try:
        size = f.content_length or 0
        if size == 0:
            pos = f.stream.tell(); f.stream.seek(0, 2); size = f.stream.tell(); f.stream.seek(pos)
        if size == 0:
            raise ValueError("Rozmiar pliku nieznany (0 B).")

        chunk_size  = min(size, 5 * 1024 * 1024) or 1
        chunk_count = -(-size // chunk_size)

        init_resp = requests.post(
            "https://open.tiktokapis.com/v2/post/publish/inbox/video/init/",
            headers={
                "Authorization": f"Bearer {session['tiktok_access_token']}",
                "Accept": "application/json",
                "X-Client-Id": TIKTOK_CLIENT_KEY or "",
            },
            json={
                "open_id": session["tiktok_open_id"],
                "source_info": {
                    "source": "FILE_UPLOAD",
                    "video_size": size,
                    "chunk_size": chunk_size,
                    "total_chunk_count": chunk_count
                }
            }, timeout=15,
        )
        current_app.logger.debug("INIT raw: %s", init_resp.text)
        init_resp.raise_for_status()

        data = init_resp.json().get("data", {})
        # ---- kompatybilność z dwiema wersjami API ----
        video_id     = data.get("video_id")     or data.get("publish_id")
        upload_addr  = data.get("upload_address") or data.get("upload_url")
        if not video_id or not upload_addr:
            raise ValueError(f"Brak video_id/upload_address w odp.: {data}")

        # 2) UPLOAD
        put_resp = requests.put(upload_addr,
                                headers={"Content-Type": "application/octet-stream"},
                                data=f.stream, timeout=60)
        put_resp.raise_for_status()

        # 3) PUBLISH – wybór endpointu zależnie od pola
        publish_endpoint = (
            "https://open.tiktokapis.com/v2/post/publish/video/upload/"
            if "video_id" in data
            else "https://open.tiktokapis.com/v2/post/publish/inbox/video/upload/"
        )
        publish_resp = requests.post(
            publish_endpoint,
            headers={
                "Authorization": f"Bearer {session['tiktok_access_token']}",
                "Accept": "application/json",
                "X-Client-Id": TIKTOK_CLIENT_KEY or "",
            },
            json={"video_id": video_id} if "video_id" in data else {"publish_id": video_id},
            timeout=15,
        )
        current_app.logger.debug("PUBLISH raw: %s", publish_resp.text)
        publish_resp.raise_for_status()
        status = publish_resp.json().get("data", {}).get("status", "PENDING")

    except requests.HTTPError as e:
        detail = e.response.text[:400]
        flash(f"Błąd TikTok API ({e.response.status_code}): {detail}", "error")
        current_app.logger.error("[TikTok upload] %s | %s", e, detail)
        return redirect(url_for("automation.automation_tiktok_video"))

    except Exception as ex:
        flash(f"Upload error: {ex}", "error")
        current_app.logger.error("Upload crash: %s", ex)
        return redirect(url_for("automation.automation_tiktok_video"))

    flash(f"🎉 Wideo {video_id} wysłane (status: {status})!", "success")
    return redirect(url_for("automation.automation_tiktok_video"))

# ─────────────────────────  FACEBOOK PLACEHOLDER  ──────────────────
@automation_bp.route("/facebook", endpoint="automation_facebook")
def automation_facebook():
    return render_template_string("…")

@automation_bp.route("/facebook/publish", methods=["GET", "POST"], endpoint="automation_facebook_publish")
def automation_facebook_publish():
    if request.method == "GET":
        return render_template_string("…")
    publish_post_to_facebook(request.form["content"])
    flash("Opublikowano na Facebooku.", "success")
    return redirect(url_for("automation.automation_facebook"))
