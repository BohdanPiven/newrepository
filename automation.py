# automation.py  – Blueprint zarządzający automatyzacją (TikTok, Facebook, itp.)

from flask import (
    Blueprint, render_template_string, url_for,
    request, flash, redirect, session
)
from datetime import datetime
import requests
from app import db  # import instancji SQLAlchemy z Twojego pliku głównego (app.py)
from automation_models import ScheduledPost
from selenium_facebook_post import publish_post_to_facebook

automation_bp = Blueprint('automation', __name__, url_prefix='/automation')


@automation_bp.route('/', endpoint='automation_home')
def automation_home():
    home_template = '''
    <!DOCTYPE html>
    <html lang="pl">
    <head><meta charset="UTF-8"><title>Automation - Główna</title>
      <style>
        *{margin:0;padding:0;box-sizing:border-box;}
        body{font-family:Arial,sans-serif;background:#f2f2f2;}
        .container{max-width:600px;margin:20px auto;background:#fff;padding:20px;
          box-shadow:0 4px 8px rgba(0,0,0,0.1);position:relative;}
        .back-button{position:absolute;top:10px;left:10px;font-size:14px;
          text-decoration:none;color:#fff;background:#1f8ef1;padding:6px 10px;
          border-radius:4px;display:inline-flex;align-items:center;}
        .back-button:hover{background:#0a6db9;}
        .back-button:before{content:"←";margin-right:5px;}
        .platform-list a{display:block;margin:6px 0;padding:8px 12px;
          background:#1f8ef1;color:#fff;text-decoration:none;border-radius:4px;}
        .platform-list a:hover{background:#0a6db9;}
      </style>
    </head><body>
      <div class="container">
        <a href="{{ url_for('index') }}" class="back-button">back</a>
        <h1>Panel Automatyzacji</h1>
        <p>Wybierz platformę, którą chcesz konfigurować lub automatyzować:</p>
        <div class="platform-list">
          <a href="{{ url_for('automation.automation_tiktok') }}">TikTok</a>
          <a href="{{ url_for('automation.automation_facebook') }}">Facebook</a>
        </div>
      </div>
    </body></html>'''
    return render_template_string(home_template)


@automation_bp.route('/tiktok')
def automation_tiktok():
    tiktok_template = '''
    <!DOCTYPE html>
    <html lang="pl">
    <head><meta charset="UTF-8"><title>Automatyzacja TikTok</title>
      <style>
        body{font-family:Arial,sans-serif;background:#f2f2f2;}
        .container{max-width:800px;margin:50px auto;background:#fff;
          padding:20px;border-radius:8px;box-shadow:0 2px 5px rgba(0,0,0,0.2);}
        h1{margin-bottom:20px;}
        nav a{margin:0 10px;text-decoration:none;color:#1f8ef1;}
        nav a:hover{text-decoration:underline;}
        .login-link,.logout-link{display:inline-block;margin-top:20px;
          padding:10px 15px;background:#1f8ef1;color:#fff;text-decoration:none;
          border-radius:4px;}
        .login-link:hover,.logout-link:hover{background:#0a6db9;}
        .user-info{margin-top:10px;color:#555;}
      </style>
    </head><body>
      <div class="container">
        <h1>Automatyzacja TikTok</h1>
        {% if session.get('tiktok_open_id') %}
          <p class="user-info">✅ Połączono jako <code>{{ session.tiktok_open_id }}</code></p>
          <a href="{{ url_for('tiktok_auth.logout') }}" class="logout-link">Wyloguj się</a>
        {% else %}
          <a href="{{ url_for('tiktok_auth.login') }}" class="login-link">Zaloguj się przez TikTok</a>
        {% endif %}
        <nav>
          <a href="{{ url_for('automation.automation_tiktok') }}">Główna</a> |
          <a href="{{ url_for('automation.automation_tiktok_plan') }}">Plan treści</a> |
          <a href="{{ url_for('automation.automation_tiktok_rodzaje') }}">Rodzaje</a> |
          <a href="{{ url_for('automation.automation_tiktok_scenariusze') }}">Scenariusze</a> |
          <a href="{{ url_for('automation.automation_tiktok_timeline') }}">Timeline</a> |
          <a href="{{ url_for('automation.automation_tiktok_video') }}">Wideo</a>
        </nav>
        <hr>
        <p>Tu możesz skonfigurować automatyzację i plan publikacji na TikToku.</p>
        <p><a href="{{ url_for('automation.automation_home') }}">Powrót do listy platform</a></p>
      </div>
    </body></html>'''
    return render_template_string(tiktok_template)


@automation_bp.route('/tiktok/plan', methods=['GET','POST'])
def automation_tiktok_plan():
    if 'tiktok_open_id' not in session:
        flash("Musisz się połączyć z TikTok Sandbox.", "error")
        return redirect(url_for('automation.automation_tiktok'))

    user_id = session['tiktok_open_id']
    if request.method == 'POST':
        d = datetime.strptime(request.form['post_date'], "%Y-%m-%d").date()
        t = datetime.strptime(request.form['post_time'], "%H:%M").time()
        new = ScheduledPost(
            date=d, time=t,
            topic=request.form['topic'],
            description=request.form['description'],
            user_id=user_id
        )
        db.session.add(new)
        db.session.commit()
        flash("Dodano nowy wpis.", "success")
        return redirect(url_for('automation.automation_tiktok_plan'))

    posts = ScheduledPost.query \
        .filter_by(user_id=user_id) \
        .order_by(ScheduledPost.date, ScheduledPost.time) \
        .all()

    plan_template = '''
    <!DOCTYPE html><html lang="pl"><head><meta charset="UTF-8">
    <title>Plan treści TikTok</title>
    <style>
      body{font-family:Arial,sans-serif;background:#f2f2f2;}
      .container{max-width:600px;margin:50px auto;background:#fff;padding:20px;
        border-radius:8px;box-shadow:0 2px 5px rgba(0,0,0,0.2);}
      h1{margin-bottom:20px;}
      ul{list-style:none;padding-left:0;}
      li{margin-bottom:8px;}
      form label{display:block;margin:8px 0;}
      input, textarea{width:100%;padding:8px;border:1px solid #ccc;
        border-radius:4px;}
      button{margin-top:10px;padding:10px 20px;background:#1f8ef1;color:#fff;
        border:none;border-radius:4px;cursor:pointer;}
      button:hover{background:#0a6db9;}
      a.back{display:inline-block;margin-top:20px;color:#555;text-decoration:none;}
      a.back:hover{text-decoration:underline;}
    </style>
    </head><body>
      <div class="container">
        <h1>Plan treści TikTok</h1>
        <ul>
          {% for p in posts %}
            <li>{{ p.date }} {{ p.time }} – {{ p.topic }}</li>
          {% endfor %}
        </ul>
        <form method="post">
          <label>Data: <input type="date" name="post_date" required></label>
          <label>Czas: <input type="time" name="post_time" required></label>
          <label>Tytuł: <input name="topic" required></label>
          <label>Opis: <textarea name="description" rows="3"></textarea></label>
          <button type="submit">Dodaj</button>
        </form>
        <a href="{{ url_for('automation.automation_tiktok') }}" class="back">← Powrót</a>
      </div>
    </body></html>'''
    return render_template_string(plan_template, posts=posts)


@automation_bp.route('/tiktok/rodzaje')
def automation_tiktok_rodzaje():
    tpl = '''
    <!DOCTYPE html><html lang="pl"><head><meta charset="UTF-8">
    <title>Rodzaje wideo (TikTok)</title></head><body>
      <h1>Rodzaje wideo na TikToku</h1>
      <p>Krótki opis: poradniki, Q&A, kulisy pracy itp.</p>
      <p><a href="{{ url_for('automation.automation_tiktok') }}">← Powrót</a></p>
    </body></html>'''
    return render_template_string(tpl)


@automation_bp.route('/tiktok/scenariusze')
def automation_tiktok_scenariusze():
    tpl = '''
    <!DOCTYPE html><html lang="pl"><head><meta charset="UTF-8">
    <title>Scenariusze Postów (TikTok)</title></head><body>
      <h1>Scenariusze Postów i Wytyczne</h1>
      <p>Przykładowe schematy i wytyczne.</p>
      <p><a href="{{ url_for('automation.automation_tiktok') }}">← Powrót</a></p>
    </body></html>'''
    return render_template_string(tpl)


@automation_bp.route('/tiktok/timeline')
def automation_tiktok_timeline():
    tpl = '''
    <!DOCTYPE html><html lang="pl"><head><meta charset="UTF-8">
    <title>Timeline TikTok</title>
      <link href="https://cdnjs.cloudflare.com/ajax/libs/fullcalendar/5.11.3/main.min.css" rel="stylesheet"/>
      <style>.container{max-width:900px;margin:50px auto;background:#fff;padding:20px;
        border-radius:8px;box-shadow:0 2px 5px rgba(0,0,0,0.2);}</style>
    </head><body>
      <div class="container">
        <h1>Timeline TikTok</h1>
        <div id="calendar"></div>
        <p><a href="{{ url_for('automation.automation_tiktok') }}">← Powrót</a></p>
      </div>
      <script src="https://cdnjs.cloudflare.com/ajax/libs/fullcalendar/5.11.3/main.min.js"></script>
      <script>
        document.addEventListener('DOMContentLoaded', function() {
          var calendarEl = document.getElementById('calendar');
          var calendar = new FullCalendar.Calendar(calendarEl, {
            initialView: 'dayGridMonth',
            events: [
              {% for p in posts %}
                {
                  title: '{{ p.topic }}',
                  start: '{{ p.date }}T{{ p.time }}'
                },
              {% endfor %}
            ]
          });
          calendar.render();
        });
      </script>
    </body></html>'''
    # pobierz też zaplanowane wpisy, jak wyżej
    posts = ScheduledPost.query \
        .filter_by(user_id=session.get('tiktok_open_id')) \
        .order_by(ScheduledPost.date, ScheduledPost.time) \
        .all()
    return render_template_string(tpl, posts=posts)


@automation_bp.route('/tiktok/video', methods=['GET','POST'])
def automation_tiktok_video():
    if 'tiktok_access_token' not in session:
        flash("Musisz być zalogowany, aby uploadować wideo.", "error")
        return redirect(url_for('automation.automation_tiktok'))

    token = session['tiktok_access_token']
    if request.method == 'POST':
        f = request.files.get('video')
        if not f:
            flash("Nie wybrano pliku.", "error")
            return redirect(url_for('automation.automation_tiktok_video'))

        data = f.read()
        size = len(data)

        # 1. INIT
        init_resp = requests.post(
            'https://open.tiktokapis.com/v2/post/publish/video/init/',
            headers={
                'Authorization': f'Bearer {token}',
                'Content-Type': 'application/json; charset=UTF-8'
            },
            json={
                "post_info": {"privacy_level": "SELF_ONLY"},
                "source_info": {
                    "source": "FILE_UPLOAD",
                    "video_size": size,
                    "chunk_size": size,
                    "total_chunk_count": 1
                }
            }
        )
        if not init_resp.ok:
            flash(f"Init upload failed: {init_resp.text}", "error")
            return redirect(url_for('automation.automation_tiktok_video'))

        init_json = init_resp.json().get('data', {})
        upload_url = init_json.get('upload_url')
        publish_id = init_json.get('publish_id')

        # 2. UPLOAD (PUT)
        put_resp = requests.put(
            upload_url,
            data=data,
            headers={
                'Content-Type': f.mimetype,
                'Content-Length': str(size),
                'Content-Range': f'bytes 0-{size-1}/{size}'
            }
        )
        if not put_resp.ok:
            flash(f"Upload video failed: {put_resp.status_code}", "error")
        else:
            flash(f"Wideo wysłane do sandbox. publish_id: {publish_id}", "success")

        return redirect(url_for('automation.automation_tiktok_video'))

    video_template = '''
    <!DOCTYPE html><html lang="pl"><head><meta charset="UTF-8">
    <title>Upload Wideo TikTok</title>
    <style>
      body{font-family:Arial,sans-serif;background:#f2f2f2;}
      .container{max-width:600px;margin:50px auto;background:#fff;padding:20px;
        border-radius:8px;box-shadow:0 2px 5px rgba(0,0,0,0.2);}
      h1{margin-bottom:20px;}
      .nav a{margin-right:10px;text-decoration:none;color:#1f8ef1;}
      .nav a:hover{text-decoration:underline;}
      .flash{padding:10px;border-radius:4px;margin-bottom:15px;}
      .flash.error{background:#fdd;color:#900;}
      .flash.success{background:#dfd;color:#090;}
      form input{display:block;margin:15px 0;}
      button{padding:10px 20px;background:#1f8ef1;color:#fff;
        border:none;border-radius:4px;cursor:pointer;}
      button:hover{background:#0a6db9;}
    </style>
    </head><body>
      <div class="container">
        <h1>Upload Wideo</h1>
        <div class="nav">
          <a href="{{ url_for('automation.automation_tiktok') }}">Główna</a> |
          <a href="{{ url_for('automation.automation_tiktok_plan') }}">Plan treści</a> |
          <a href="{{ url_for('automation.automation_tiktok_rodzaje') }}">Rodzaje</a> |
          <a href="{{ url_for('automation.automation_tiktok_scenariusze') }}">Scenariusze</a> |
          <a href="{{ url_for('automation.automation_tiktok_timeline') }}">Timeline</a> |
          <a href="{{ url_for('automation.automation_tiktok_video') }}">Wideo</a>
        </div>
        {% for msg in get_flashed_messages(category_filter=["error"]) %}
          <div class="flash error">{{ msg }}</div>
        {% endfor %}
        {% for msg in get_flashed_messages(category_filter=["success"]) %}
          <div class="flash success">{{ msg }}</div>
        {% endfor %}
        <form method="post" enctype="multipart/form-data">
          <label>Wybierz plik (mp4, mov):
            <input type="file" name="video" accept=".mp4,.mov" required>
          </label>
          <button type="submit">Wyślij do sandbox</button>
        </form>
        <p><a href="{{ url_for('automation.automation_tiktok') }}">← Powrót</a></p>
      </div>
    </body></html>'''
    return render_template_string(video_template)


@automation_bp.route('/facebook')
def automation_facebook():
    tpl = '''
    <!DOCTYPE html><html lang="pl"><head><meta charset="UTF-8">
    <title>Automatyzacja Facebook</title></head><body>
      <h1>Automatyzacja Facebook</h1>
      <p>Placeholder...</p>
      <p><a href="{{ url_for('automation.automation_home') }}">← Powrót</a></p>
    </body></html>'''
    return render_template_string(tpl)


@automation_bp.route('/facebook/publish', methods=['GET','POST'])
def automation_facebook_publish():
    if request.method == 'GET':
        return render_template_string('''
          <h1>Publikuj na Facebooku</h1>
          <form method="post"><textarea name="content"></textarea><br>
            <button type="submit">Publikuj</button>
          </form>''')
    publish_post_to_facebook(request.form['content'])
    flash("Opublikowano na Facebooku.", "success")
    return redirect(url_for('automation.automation_facebook_publish'))
