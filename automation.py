# automation.py
import math, mimetypes, requests, logging, io
from datetime import datetime
from os import getenv
from flask import (
    Blueprint, render_template_string, url_for, request,
    flash, redirect, session, jsonify, get_flashed_messages, current_app
)

from app import db
from automation_models import ScheduledPost
from selenium_facebook_post import publish_post_to_facebook

TIKTOK_CLIENT_KEY = getenv("TIKTOK_CLIENT_KEY", "")

automation_bp = Blueprint("automation", __name__, url_prefix="/automation")
logger = logging.getLogger(__name__)

# ─────────────────────────  PANEL HOME  ────────────────────────────
@automation_bp.route("/", endpoint="automation_home")
def automation_home():
    return render_template_string(
        """<!DOCTYPE html><html lang="pl"><head><meta charset="UTF-8">
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
    )

# ─────────────────────  TIKTOK GŁÓWNA  ────────────────────────────
@automation_bp.route("/tiktok", endpoint="automation_tiktok")
def automation_tiktok():
    return render_template_string(
        """<!DOCTYPE html><html lang="pl"><head><meta charset="UTF-8">
        <title>Automatyzacja TikTok</title><style>
          body{font-family:Arial,sans-serif;background:#f2f2f2;}
          .container{max-width:800px;margin:50px auto;background:#fff;padding:20px;border-radius:8px;box-shadow:0 2px 5px rgba(0,0,0,0.2);}
          nav a{margin:0 10px;color:#1f8ef1;text-decoration:none;}nav a:hover{text-decoration:underline;}
          .login-link{display:inline-block;margin-top:20px;padding:10px 15px;background:#1f8ef1;color:#fff;text-decoration:none;border-radius:4px;}
          .login-link:hover{background:#0a6db9;}
        </style></head><body>
          <div class="container">
            <h1>Automatyzacja TikTok</h1>
            <nav>
              <a href="{{ url_for('automation.automation_home') }}">Główna</a> |
              <a href="{{ url_for('automation.automation_tiktok_plan') }}">Plan treści</a> |
              <a href="{{ url_for('automation.automation_tiktok_rodzaje') }}">Rodzaje</a> |
              <a href="{{ url_for('automation.automation_tiktok_scenariusze') }}">Scenariusze</a> |
              <a href="{{ url_for('automation.automation_tiktok_timeline') }}">Timeline</a> |
              <a href="{{ url_for('automation.automation_tiktok_video') }}">Wideo</a>
            </nav><hr>
            {% set succ = get_flashed_messages(category_filter=['success']) %}
            {% set err  = get_flashed_messages(category_filter=['error']) %}
            {% if succ %}<div style='background:#dfd;padding:10px;border-radius:4px'>{{ succ[-1] }}</div>{% elif err %}
              <div style='background:#fdd;padding:10px;border-radius:4px'>{{ err[-1] }}</div>{% endif %}
            {% if session.get('tiktok_open_id') %}
              <p>✅ Połączono jako <code>{{ session.tiktok_open_id }}</code></p>
              <a href="{{ url_for('tiktok_auth.logout') }}" class="login-link">Wyloguj się</a>
            {% else %}
              <a href="{{ url_for('tiktok_auth.login') }}" class="login-link">Zaloguj się przez TikTok</a>
            {% endif %}
          </div></body></html>"""
    )

# ──────────────────────  PLAN TREŚCI  ──────────────────────────────
@automation_bp.route("/tiktok/plan", methods=["GET", "POST"], endpoint="automation_tiktok_plan")
def automation_tiktok_plan():
    if "tiktok_open_id" not in session:
        flash("Musisz się połączyć z TikTok.", "error")
        return redirect(url_for("automation.automation_tiktok"))

    uid = session["tiktok_open_id"]
    if request.method == "POST":
        d = datetime.strptime(request.form["post_date"], "%Y-%m-%d").date()
        t = datetime.strptime(request.form["post_time"], "%H:%M").time()
        db.session.add(ScheduledPost(
            date=d, time=t, topic=request.form["topic"],
            description=request.form["description"], user_id=uid))
        db.session.commit(); flash("Dodano wpis.", "success")
        return redirect(url_for("automation.automation_tiktok_plan"))

    posts = (ScheduledPost.query.filter_by(user_id=uid)
             .order_by(ScheduledPost.date.asc(), ScheduledPost.time.asc()).all())
    return render_template_string(
        """<!DOCTYPE html><html lang="pl"><head><meta charset="UTF-8">
        <title>Plan treści TikTok</title><style>body{font-family:Arial;padding:20px}</style></head><body>
          <h1>Plan treści TikTok</h1>
          <ul>{% for p in posts %}<li>{{ p.date }} {{ p.time }} – {{ p.topic }}</li>{% endfor %}</ul>
          <form method="post">
            <label>Data: <input type="date" name="post_date" required></label><br>
            <label>Czas: <input type="time" name="post_time" required></label><br>
            <label>Tytuł: <input name="topic" required></label><br>
            <label>Opis: <textarea name="description"></textarea></label><br>
            <button type="submit">Dodaj</button>
          </form>
          <p><a href="{{ url_for('automation.automation_tiktok') }}">← Powrót</a></p>
        </body></html>""", posts=posts)

# ───────────────────  FULLCALENDAR EVENTS  ──────────────────────────
@automation_bp.route("/tiktok/events", endpoint="automation_tiktok_events")
def tiktok_events():
    uid = session.get("tiktok_open_id")
    if not uid:
        return jsonify([])
    return jsonify([{
        "title": p.topic,
        "start": f"{p.date.isoformat()}T{p.time.strftime('%H:%M:%S')}",
        "url": url_for("automation.automation_tiktok_plan"),
    } for p in ScheduledPost.query.filter_by(user_id=uid).all()])

# ───────────────────  TIMELINE (FULLCALENDAR)  ─────────────────────
@automation_bp.route("/tiktok/timeline", endpoint="automation_tiktok_timeline")
def automation_tiktok_timeline():
    return render_template_string(
        """<!DOCTYPE html><html lang="pl"><head><meta charset="UTF-8">
        <title>Timeline TikTok</title>
        <link href="https://cdn.jsdelivr.net/npm/fullcalendar@6.1.8/index.global.min.css" rel="stylesheet">
        <style>body{font-family:Arial;background:#f2f2f2;padding:20px}
          .card{max-width:900px;margin:20px auto;background:#fff;padding:20px;border-radius:8px;box-shadow:0 2px 5px rgba(0,0,0,0.1);}
          nav a{margin:0 10px;color:#1f8ef1;text-decoration:none;}nav a:hover{text-decoration:underline;}
        </style></head><body>
          <div class="card">
            <h1>Timeline TikTok</h1>
            <nav>
              <a href="{{ url_for('automation.automation_home') }}">Główna</a> |
              <a href="{{ url_for('automation.automation_tiktok_plan') }}">Plan treści</a> |
              <a href="{{ url_for('automation.automation_tiktok_rodzaje') }}">Rodzaje</a> |
              <a href="{{ url_for('automation.automation_tiktok_scenariusze') }}">Scenariusze</a> |
              <a href="{{ url_for('automation.automation_tiktok_timeline') }}">Timeline</a> |
              <a href="{{ url_for('automation.automation_tiktok_video') }}">Wideo</a>
            </nav>
            <div id="calendar" style="margin-top:20px"></div>
            <p><a href="{{ url_for('automation.automation_tiktok') }}">← Powrót</a></p>
          </div>
          <script src="https://cdn.jsdelivr.net/npm/fullcalendar@6.1.8/index.global.min.js"></script>
          <script>
            document.addEventListener('DOMContentLoaded', () =>
              new FullCalendar.Calendar(document.getElementById('calendar'),
              {initialView:'dayGridMonth',locale:'pl',
               events:'{{ url_for("automation.automation_tiktok_events") }}'}).render());
          </script></body></html>"""
    )

# ──────────  ROUTES STATYCZNE  ──────────────────────────────────────
@automation_bp.route("/tiktok/rodzaje", endpoint="automation_tiktok_rodzaje")
def automation_tiktok_rodzaje():
    return render_template_string("""<!DOCTYPE html><html lang="pl"><head>
      <meta charset="UTF-8"><title>Rodzaje wideo</title></head><body style="font-family:Arial;padding:20px">
        <h1>Rodzaje wideo na TikToku</h1><p>Poradniki, Q&A, kulisy pracy…</p>
        <p><a href="{{ url_for('automation.automation_tiktok') }}">← Powrót</a></p>
      </body></html>""")

@automation_bp.route("/tiktok/scenariusze", endpoint="automation_tiktok_scenariusze")
def automation_tiktok_scenariusze():
    return render_template_string("""<!DOCTYPE html><html lang="pl"><head>
      <meta charset="UTF-8"><title>Scenariusze</title></head><body style="font-family:Arial;padding:20px">
        <h1>Scenariusze Postów i Wytyczne</h1><p>Przykładowe schematy…</p>
        <p><a href="{{ url_for('automation.automation_tiktok') }}">← Powrót</a></p>
      </body></html>""")

# ───────────────────  UPLOAD WIDEO  ────────────────────────────────
@automation_bp.route("/tiktok/video", methods=["GET", "POST"], endpoint="automation_tiktok_video")
def automation_tiktok_video():
    if "tiktok_open_id" not in session:
        flash("Musisz się połączyć z TikTok.", "error")
        return redirect(url_for("automation.automation_tiktok"))

    # ---------- formularz ----------
    if request.method == "GET":
        return render_template_string("""<!DOCTYPE html><html lang="pl"><head>
          <meta charset="UTF-8"><title>Upload wideo TikTok</title></head><body style="font-family:Arial;padding:20px">
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
        # 1) INIT
        size = f.content_length or 0
        if size == 0:
            pos = f.stream.tell(); f.stream.seek(0, 2); size = f.stream.tell(); f.stream.seek(pos)
        if size == 0:
            raise ValueError("Nie mogę ustalić rozmiaru pliku (0 B).")

        chunk_size  = min(size, 5 * 1024 * 1024)
        chunk_count = math.ceil(size / chunk_size)

        init_body = {
            "open_id": session["tiktok_open_id"],
            "source_info": {
                "source": "FILE_UPLOAD",
                "video_size": size,
                "chunk_size": chunk_size,
                "total_chunk_count": chunk_count
            }
        }
        init = requests.post(
            "https://open.tiktokapis.com/v2/post/publish/inbox/video/init/",
            headers={"Authorization": f"Bearer {session['tiktok_access_token']}",
                     "Accept": "application/json", "X-Client-Id": TIKTOK_CLIENT_KEY},
            json=init_body, timeout=15)
        init.raise_for_status()
        logger.debug("INIT raw: %s", init.text)
        d = init.json()["data"]
        video_id  = d.get("video_id") or d.get("publish_id")
        base_url  = d.get("upload_address") or d.get("upload_url")
        if not (video_id and base_url):
            raise RuntimeError(f"Błędna odpowiedź INIT: {d}")

        mime = mimetypes.guess_type(f.filename)[0] or "video/mp4"

        # 2) UPLOAD (≤5 MB → pojedynczy PUT; >5 MB → pętla PUT part_number=0..n-1)
        def put_chunk(url, data_bytes):
            headers = {"Content-Type": mime, "Content-Length": str(len(data_bytes))}
            r = requests.put(url, headers=headers, data=data_bytes, timeout=120)
            if r.status_code == 404:  # fallback do POST multipart (starszy sandbox)
                files = {"file": (f.filename, io.BytesIO(data_bytes), mime)}
                r = requests.post(url, files=files, timeout=120)
            r.raise_for_status()

        if chunk_count == 1:
            f.stream.seek(0); blob = f.stream.read()
            put_chunk(base_url, blob)
        else:
            for idx in range(chunk_count):
                f.stream.seek(idx * chunk_size)
                blob = f.stream.read(chunk_size)
                put_chunk(f"{base_url}&part_number={idx}", blob)

        # 3) PUBLISH
        pub_endpoint = ("https://open.tiktokapis.com/v2/post/publish/video/upload/"
                        if "video_id" in d else
                        "https://open.tiktokapis.com/v2/post/publish/inbox/video/upload/")
        pub_payload  = {"video_id": video_id} if "video_id" in d else {"publish_id": video_id}
        pub = requests.post(
            pub_endpoint,
            headers={"Authorization": f"Bearer {session['tiktok_access_token']}",
                     "Accept": "application/json", "X-Client-Id": TIKTOK_CLIENT_KEY},
            json=pub_payload, timeout=15)
        logger.debug("PUBLISH raw: %s", pub.text)
        pub.raise_for_status()
        status = pub.json().get("data", {}).get("status", "PENDING")

    except requests.HTTPError as e:
        flash(f"Błąd TikTok API {e.response.status_code}: {e.response.text[:300]}", "error")
        logger.error("HTTPError upload: %s | %s", e, e.response.text)
        return redirect(url_for("automation.automation_tiktok_video"))
    except Exception as ex:
        flash(f"Upload error: {ex}", "error")
        logger.exception("Upload crash")
        return redirect(url_for("automation.automation_tiktok_video"))

    flash(f"🎉 Wideo {video_id} wysłane (status: {status})!", "success")
    return redirect(url_for("automation.automation_tiktok_video"))

# ─────────────────────────  FACEBOOK PLACEHOLDER  ──────────────────
@automation_bp.route("/facebook", endpoint="automation_facebook")
def automation_facebook():
    return render_template_string("""<!DOCTYPE html><html lang="pl"><head>
      <meta charset="UTF-8"><title>Facebook</title></head><body style="font-family:Arial;padding:20px">
        <h1>Automatyzacja Facebook</h1><p>Placeholder…</p>
        <p><a href="{{ url_for('automation.automation_home') }}">← Powrót</a></p>
      </body></html>""")

@automation_bp.route("/facebook/publish", methods=["GET", "POST"], endpoint="automation_facebook_publish")
def automation_facebook_publish():
    if request.method == "GET":
        return render_template_string("""<!DOCTYPE html><html lang="pl"><head>
          <meta charset="UTF-8"><title>Publikuj na FB</title></head><body style="font-family:Arial;padding:20px">
            <h1>Publikuj na Facebooku</h1>
            <form method="post"><textarea name="content"></textarea><br>
              <button type="submit">Publikuj</button></form>
            <p><a href="{{ url_for('automation.automation_facebook') }}">← Powrót</a></p>
          </body></html>""")
    publish_post_to_facebook(request.form["content"])
    flash("Opublikowano na Facebooku.", "success")
    return redirect(url_for("automation.automation_facebook"))
