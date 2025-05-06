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

# ---------- tu wszystko BEZ ZMIAN do route /tiktok/video ----------

@automation_bp.route("/tiktok/video", methods=["GET", "POST"])
def automation_tiktok_video():
    if "tiktok_open_id" not in session:
        flash("Musisz się połączyć z TikTok.", "error")
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
        # -------- 1) INIT – pewne wyliczenie rozmiaru ----------
        size = f.content_length or 0
        if size == 0:
            # gdy Flask nie zna długości, obliczamy ręcznie
            pos = f.stream.tell()
            f.stream.seek(0, 2)         # EOF
            size = f.stream.tell()
            f.stream.seek(pos)           # wróć na początek
        if size == 0:
            raise ValueError("Rozmiar pliku nieznany (0 B).")

        chunk_size  = min(size, 5 * 1024 * 1024) or 1   # ≥1 B
        chunk_count = -(-size // chunk_size)            # ceil

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
            },
            timeout=15,
        )
        current_app.logger.debug("INIT raw: %s", init_resp.text)
        init_resp.raise_for_status()
        data = init_resp.json()["data"]
        video_id, upload_addr = data["video_id"], data["upload_address"]

        # -------- 2) UPLOAD ----------
        put_resp = requests.put(
            upload_addr,
            headers={"Content-Type": "application/octet-stream"},
            data=f.stream,
            timeout=60,
        )
        put_resp.raise_for_status()

        # -------- 3) PUBLISH ----------
        publish_resp = requests.post(
            "https://open.tiktokapis.com/v2/post/publish/video/upload/",
            headers={
                "Authorization": f"Bearer {session['tiktok_access_token']}",
                "Accept": "application/json",
                "X-Client-Id": TIKTOK_CLIENT_KEY or "",
            },
            json={"video_id": video_id},
            timeout=15,
        )
        current_app.logger.debug("PUBLISH raw: %s", publish_resp.text)
        publish_resp.raise_for_status()
        status = publish_resp.json().get("data", {}).get("status", "PENDING")

    except requests.HTTPError as e:
        try:
            detail = e.response.json()
        except Exception:
            detail = e.response.text[:200]
        flash(f"Błąd TikTok API ({e.response.status_code}): {detail}", "error")
        current_app.logger.error("[TikTok upload] %s | %s", e, detail)
        return redirect(url_for("automation.automation_tiktok_video"))

    except Exception as ex:
        flash(f"Nieoczekiwany błąd: {ex}", "error")
        current_app.logger.exception("Upload crash")
        return redirect(url_for("automation.automation_tiktok_video"))

    flash(f"🎉 Wideo {video_id} wysłane (status: {status})!", "success")
    return redirect(url_for("automation.automation_tiktok_video"))

# ---------- reszta pliku (timeline, FB placeholder) bez zmian ----------


automation_bp.add_url_rule(
    "/tiktok/video",
    endpoint="automation_tiktok_video",
    view_func=automation_tiktok_video,
    methods=["GET", "POST"],
)

# ─────────────────────────  FACEBOOK PLACEHOLDER  ──────────────────
@automation_bp.route("/facebook")
def automation_facebook():
    return render_template_string("""<!DOCTYPE html><html lang="pl"><head>
        <meta charset="UTF-8"><title>Facebook</title></head><body
        style="font-family:Arial,sans-serif;padding:20px">
          <h1>Automatyzacja Facebook</h1><p>Placeholder...</p>
          <p><a href="{{ url_for('automation.automation_home') }}">← Powrót</a></p>
        </body></html>""")

@automation_bp.route("/facebook/publish", methods=["GET", "POST"])
def automation_facebook_publish():
    if request.method == "GET":
        return render_template_string("""<!DOCTYPE html><html lang="pl"><head>
              <meta charset="UTF-8"><title>Publikuj na FB</title></head><body
              style="font-family:Arial,sans-serif;padding:20px">
                <h1>Publikuj na Facebooku</h1>
                <form method="post"><textarea name="content"></textarea><br>
                  <button type="submit">Publikuj</button></form>
                <p><a href="{{ url_for('automation.automation_facebook') }}">← Powrót</a></p>
              </body></html>""")
    publish_post_to_facebook(request.form["content"])
    flash("Opublikowano na Facebooku.", "success")
    return redirect(url_for("automation.automation_facebook"))
