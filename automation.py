# automation.py
import requests
from flask import (
    Blueprint, render_template_string, url_for, request,
    flash, redirect, session, jsonify, get_flashed_messages
)
from datetime import datetime
from app import db
from automation_models import ScheduledPost
from selenium_facebook_post import publish_post_to_facebook
from tiktok_auth import UPLOAD_VIDEO_URL

automation_bp = Blueprint('automation', __name__, url_prefix='/automation')


@automation_bp.route('/', endpoint='automation_home')
def automation_home():
    tpl = '''
    <!DOCTYPE html>
    <html lang="pl">
    <head><meta charset="UTF-8"><title>Panel Automatyzacji</title>
      <style>
        *{margin:0;padding:0;box-sizing:border-box;}
        body{font-family:Arial,sans-serif;background:#f2f2f2;}
        .container{max-width:600px;margin:20px auto;background:#fff;padding:20px;
          box-shadow:0 4px 8px rgba(0,0,0,0.1);position:relative;}
        .platform-list a{display:block;margin:6px 0;padding:8px 12px;
          background:#1f8ef1;color:#fff;text-decoration:none;border-radius:4px;}
        .platform-list a:hover{background:#0a6db9;}
        .back{position:absolute;top:10px;left:10px;color:#fff;
          background:#1f8ef1;padding:6px 10px;border-radius:4px;text-decoration:none;}
        .back:hover{background:#0a6db9;}
      </style>
    </head><body>
      <div class="container">
        <a href="{{ url_for('index') }}" class="back">← back</a>
        <h1>Panel Automatyzacji</h1>
        <p>Wybierz platformę:</p>
        <div class="platform-list">
          <a href="{{ url_for('automation.automation_tiktok') }}">TikTok</a>
          <a href="{{ url_for('automation.automation_facebook') }}">Facebook</a>
        </div>
      </div>
    </body></html>
    '''
    return render_template_string(tpl)


@automation_bp.route('/tiktok')
def automation_tiktok():
    tpl = '''
    <!DOCTYPE html>
    <html lang="pl">
    <head><meta charset="UTF-8"><title>Automatyzacja TikTok</title>
      <style>
        body{font-family:Arial,sans-serif;background:#f2f2f2;}
        .container{max-width:800px;margin:50px auto;background:#fff;
          padding:20px;border-radius:8px;box-shadow:0 2px 5px rgba(0,0,0,0.2);}
        h1{margin-bottom:20px;}
        nav a{margin:0 10px;color:#1f8ef1;text-decoration:none;}
        nav a:hover{text-decoration:underline;}
        .login-link{display:inline-block;margin-top:20px;
          padding:10px 15px;background:#1f8ef1;color:#fff;text-decoration:none;border-radius:4px;}
        .login-link:hover{background:#0a6db9;}
      </style>
    </head><body>
      <div class="container">
        <h1>Automatyzacja TikTok</h1>
        <nav>
          <a href="{{ url_for('automation.automation_home') }}">Główna</a> |
          <a href="{{ url_for('automation.automation_tiktok_plan') }}">Plan treści</a> |
          <a href="{{ url_for('automation.automation_tiktok_rodzaje') }}">Rodzaje</a> |
          <a href="{{ url_for('automation.automation_tiktok_scenariusze') }}">Scenariusze</a> |
          <a href="{{ url_for('automation.automation_tiktok_timeline') }}">Timeline</a> |
          <a href="{{ url_for('automation.automation_tiktok_video') }}">Wideo</a>
        </nav>
        <hr>
        {% set succ = get_flashed_messages(category_filter=['success']) %}
        {% set err  = get_flashed_messages(category_filter=['error']) %}
        {% if succ %}<div style="background:#dfd;padding:10px;border-radius:4px">{{ succ[-1] }}</div>{% elif err %}<div style="background:#fdd;padding:10px;border-radius:4px">{{ err[-1] }}</div>{% endif %}
        {% if session.get('tiktok_open_id') %}
          <p>✅ Połączono jako <code>{{ session.tiktok_open_id }}</code></p>
          <a href="{{ url_for('tiktok_auth.logout') }}" class="login-link">Wyloguj się</a>
        {% else %}
          <a href="{{ url_for('tiktok_auth.login') }}" class="login-link">Zaloguj się przez TikTok</a>
        {% endif %}
      </div>
    </body></html>
    '''
    return render_template_string(tpl)


@automation_bp.route('/tiktok/plan', methods=['GET','POST'])
def automation_tiktok_plan():
    if 'tiktok_open_id' not in session:
        flash("Musisz się połączyć z TikTok.", "error")
        return redirect(url_for('automation.automation_tiktok'))

    uid = session['tiktok_open_id']
    if request.method == 'POST':
        d = datetime.strptime(request.form['post_date'], "%Y-%m-%d").date()
        t = datetime.strptime(request.form['post_time'], "%H:%M").time()
        new = ScheduledPost(date=d, time=t,
                            topic=request.form['topic'],
                            description=request.form['description'],
                            user_id=uid)
        db.session.add(new); db.session.commit()
        flash("Dodano wpis.", "success")
        return redirect(url_for('automation.automation_tiktok_plan'))

    posts = ScheduledPost.query.filter_by(user_id=uid)\
             .order_by(ScheduledPost.date.asc(), ScheduledPost.time.asc()).all()
    tpl = '''
    <!DOCTYPE html><html lang="pl"><head><meta charset="UTF-8"><title>Plan treści TikTok</title>
      <style>body{font-family:Arial,sans-serif;padding:20px}</style>
    </head><body>
      <h1>Plan treści TikTok</h1>
      <ul>
        {% for p in posts %}
          <li>{{ p.date }} {{ p.time }} – {{ p.topic }}</li>
        {% endfor %}
      </ul>
      <form method="post">
        <label>Data: <input type="date" name="post_date" required></label><br>
        <label>Czas: <input type="time" name="post_time" required></label><br>
        <label>Tytuł: <input name="topic" required></label><br>
        <label>Opis: <textarea name="description"></textarea></label><br>
        <button type="submit">Dodaj</button>
      </form>
      <p><a href="{{ url_for('automation.automation_tiktok') }}">← Powrót</a></p>
    </body></html>
    '''
    return render_template_string(tpl, posts=posts)


@automation_bp.route('/tiktok/events')
def tiktok_events():
    """Zwraca listę wydarzeń w formacie FullCalendar JSON."""
    uid = session.get('tiktok_open_id')
    if not uid:
        return jsonify([])

    evts = []
    for p in ScheduledPost.query.filter_by(user_id=uid).all():
        evts.append({
            "title": p.topic,
            "start": f"{p.date.isoformat()}T{p.time.strftime('%H:%M:%S')}",
            "url": url_for('automation.automation_tiktok_plan')
        })
    return jsonify(evts)


@automation_bp.route('/tiktok/timeline')
def automation_tiktok_timeline():
    tpl = '''
    <!DOCTYPE html><html lang="pl"><head><meta charset="UTF-8">
      <title>Timeline TikTok</title>
      <link href="https://cdn.jsdelivr.net/npm/fullcalendar@6.1.8/index.global.min.css" rel="stylesheet">
      <style>body{font-family:Arial,sans-serif;background:#f2f2f2;padding:20px}
        .card{max-width:900px;margin:20px auto;background:#fff;padding:20px;border-radius:8px;box-shadow:0 2px 5px rgba(0,0,0,0.1);}
        nav a{margin:0 10px;color:#1f8ef1;text-decoration:none;}
        nav a:hover{text-decoration:underline;}
      </style>
    </head><body>
      <div class="card">
        <h1>Timeline TikTok</h1>
        <nav>
          <a href="{{ url_for('automation.automation_home') }}">Główna</a> |
          <a href="{{ url_for('automation.automation_tiktok_plan') }}">Plan treści</a> |
          <a href="{{ url_for('automation.automation_tiktok_rodzaje') }}">Rodzaje</a> |
          <a href="{{ url_for('automation.automation_tiktok_scenariusze') }}">Scenariusze</a> |
          <a href="{{ url_for('automation.automation_tiktok_timeline') }}">Timeline</a>
        </nav>
        <div id="calendar" style="margin-top:20px"></div>
        <p><a href="{{ url_for('automation.automation_tiktok') }}">← Powrót</a></p>
      </div>

      <script src="https://cdn.jsdelivr.net/npm/fullcalendar@6.1.8/index.global.min.js"></script>
      <script>
        document.addEventListener('DOMContentLoaded', function() {
          var calendarEl = document.getElementById('calendar');
          var calendar = new FullCalendar.Calendar(calendarEl, {
            initialView: 'dayGridMonth',
            locale: 'pl',
            events: '{{ url_for("automation.tiktok_events") }}'
          });
          calendar.render();
        });
      </script>
    </body></html>
    '''
    return render_template_string(tpl)

@automation_bp.route('/tiktok/rodzaje')
def automation_tiktok_rodzaje():
    tpl = '''
    <!DOCTYPE html><html lang="pl"><head><meta charset="UTF-8"><title>Rodzaje wideo</title></head>
    <body style="font-family:Arial,sans-serif;padding:20px">
      <h1>Rodzaje wideo na TikToku</h1>
      <p>Poradniki, Q&A, kulisy pracy itp.</p>
      <p><a href="{{ url_for('automation.automation_tiktok') }}">← Powrót</a></p>
    </body></html>
    '''
    return render_template_string(tpl)


@automation_bp.route('/tiktok/scenariusze')
def automation_tiktok_scenariusze():
    tpl = '''
    <!DOCTYPE html><html lang="pl"><head><meta charset="UTF-8"><title>Scenariusze</title></head>
    <body style="font-family:Arial,sans-serif;padding:20px">
      <h1>Scenariusze Postów i Wytyczne</h1>
      <p>Przykładowe schematy i wytyczne.</p>
      <p><a href="{{ url_for('automation.automation_tiktok') }}">← Powrót</a></p>
    </body></html>
    '''
    return render_template_string(tpl)

@automation_bp.route('/tiktok/video', methods=['GET', 'POST'])
def automation_tiktok_video():
    if 'tiktok_open_id' not in session:
        flash("Musisz się połączyć z TikTok.", "error")
        return redirect(url_for('automation.automation_tiktok'))

    tpl = '''
    <!DOCTYPE html><html lang="pl"><head><meta charset="UTF-8"><title>Wideo TikTok</title>
      <style>body{font-family:Arial,sans-serif;padding:20px}
             form{margin-top:20px;}
             input[type=file]{display:block;margin-bottom:10px;}
             .back{display:block;margin-top:20px;}
      </style>
    </head><body>
      <h1>Wyślij wideo do TikTok Sandbox</h1>
      {% if session.get('tiktok_access_token') %}
        <form method="post" enctype="multipart/form-data">
          <label>Plik (mp4/mov): <input type="file" name="video_file" accept=".mp4,.mov" required></label><br>
          <button type="submit">Wyślij do sandbox</button>
        </form>
      {% else %}
        <p style="color:red;">Musisz być zalogowany przez TikTok, aby wysłać wideo.</p>
      {% endif %}
      <p><a href="{{ url_for('automation.automation_tiktok') }}" class="back">← Powrót</a></p>
    </body></html>
    '''

    if request.method == 'POST':
        vid = request.files.get('video_file')
        if not vid:
            flash("Nie wybrano pliku.", "error")
            return redirect(url_for('automation.automation_tiktok_video'))

        # wysyłka do API TikToka
        access_token = session['tiktok_access_token']
        files = {
            'video_file': (vid.filename, vid.stream.read(), 'application/octet-stream')
        }
        headers = {
            'Authorization': f'Bearer {access_token}'
        }
        # endpoint sandboxowy:
        resp = requests.post(
            UPLOAD_VIDEO_URL,
            headers=headers,
            files=files,
            data={'open_id': session['tiktok_open_id']}
        )
        if resp.ok:
            flash("Wideo wysłano pomyślnie.", "success")
        else:
            flash(f"Błąd wysyłki wideo: {resp.status_code} {resp.text}", "error")
        return redirect(url_for('automation.automation_tiktok_video'))

    return render_template_string(tpl)


@automation_bp.route('/facebook')
def automation_facebook():
    tpl = '''
    <!DOCTYPE html><html lang="pl"><head><meta charset="UTF-8"><title>Facebook</title></head>
    <body style="font-family:Arial,sans-serif;padding:20px">
      <h1>Automatyzacja Facebook</h1>
      <p>Placeholder...</p>
      <p><a href="{{ url_for('automation.automation_home') }}">← Powrót</a></p>
    </body></html>
    '''
    return render_template_string(tpl)


@automation_bp.route('/facebook/publish', methods=['GET','POST'])
def automation_facebook_publish():
    if request.method == 'GET':
        return render_template_string('''
          <!DOCTYPE html><html lang="pl"><head><meta charset="UTF-8"><title>Publikuj na FB</title></head>
          <body style="font-family:Arial,sans-serif;padding:20px">
            <h1>Publikuj na Facebooku</h1>
            <form method="post"><textarea name="content"></textarea><br>
            <button type="submit">Publikuj</button></form>
            <p><a href="{{ url_for('automation.automation_facebook') }}">← Powrót</a></p>
          </body></html>''')
    publish_post_to_facebook(request.form['content'])
    flash("Opublikowano na Facebooku.", "success")
    return redirect(url_for('automation.automation_facebook'))