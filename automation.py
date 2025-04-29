# automation.py  – Blueprint zarządzający automatyzacją (TikTok, Facebook, itp.)

import os
import requests
from flask import (
    Blueprint, render_template_string, url_for, request,
    flash, redirect, session, current_app
)
from datetime import datetime
from app import db  # instancja SQLAlchemy z app.py
from automation_models import ScheduledPost
from selenium_facebook_post import publish_post_to_facebook

automation_bp = Blueprint('automation', __name__, url_prefix='/automation')


# --- Wspólna część navbar dla TikToka ---
_tiktok_nav = '''
    <nav style="margin-bottom:1rem;">
      <a href="{{ url_for('automation.automation_tiktok') }}">Główna</a> |
      <a href="{{ url_for('automation.automation_tiktok_plan') }}">Plan treści</a> |
      <a href="{{ url_for('automation.automation_tiktok_rodzaje') }}">Rodzaje</a> |
      <a href="{{ url_for('automation.automation_tiktok_scenariusze') }}">Scenariusze</a> |
      <a href="{{ url_for('automation.automation_tiktok_timeline') }}">Timeline</a> |
      <a href="{{ url_for('automation.automation_tiktok_video') }}">Wideo</a>
    </nav>
'''


@automation_bp.route('/', endpoint='automation_home')
def automation_home():
    """Strona główna panelu automatyzacji."""
    tpl = '''
    <!doctype html><html lang="pl"><head><meta charset="utf-8"><title>Automation - Główna</title>
    <style>
      *{margin:0;padding:0;box-sizing:border-box;}
      body{font-family:Arial,sans-serif;background:#f2f2f2;}
      .container{max-width:600px;margin:20px auto;background:#fff;padding:20px;
        box-shadow:0 4px 8px rgba(0,0,0,0.1);position:relative;}
      .back-button{position:absolute;top:10px;left:10px;font-size:14px;
        text-decoration:none;color:#fff;background:#1f8ef1;padding:6px 10px;border-radius:4px;
        display:inline-flex;align-items:center;}
      .back-button:hover{background:#0a6db9;}
      .back-button:before{content:"←";margin-right:5px;}
      h1{margin-bottom:10px;}
      .platform-list a{display:block;margin:6px 0;padding:8px 12px;
        background:#1f8ef1;color:#fff;text-decoration:none;border-radius:4px;}
      .platform-list a:hover{background:#0a6db9;}
    </style>
    </head><body>
      <div class="container">
        <a href="{{ url_for('index') }}" class="back-button">back</a>
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


# -------------------------------------------------
#      TIKTOK
# -------------------------------------------------
@automation_bp.route('/tiktok')
def automation_tiktok():
    """Strona główna automatyzacji TikTok."""
    tpl = '''
    <!doctype html><html lang="pl"><head><meta charset="utf-8"><title>Automatyzacja TikTok</title>
    <style>
      body{font-family:Arial,sans-serif;background:#f2f2f2;}
      .container{max-width:800px;margin:50px auto;background:#fff;padding:20px;
        border-radius:8px;box-shadow:0 2px 5px rgba(0,0,0,0.2);}
      h1{margin-bottom:10px;}
      a.login, a.logout{display:inline-block;margin-top:20px;padding:10px 15px;
        background:#1f8ef1;color:#fff;text-decoration:none;border-radius:4px;}
      a.login:hover, a.logout:hover{background:#0a6db9;}
    </style>
    </head><body>
      <div class="container">
        <h1>Automatyzacja TikTok</h1>
        ''' + _tiktok_nav + '''
        <hr>
        {% if session.get('tiktok_access_token') %}
          <p>✅ Połączono jako <code>{{ session.tiktok_open_id }}</code></p>
          <a href="{{ url_for('tiktok_auth.logout') }}" class="logout">Wyloguj się</a>
        {% else %}
          <a href="{{ url_for('tiktok_auth.login') }}" class="login">Zaloguj się przez TikTok</a>
        {% endif %}
        <p><a href="{{ url_for('automation.automation_home') }}">Powrót do listy platform</a></p>
      </div>
    </body></html>
    '''
    return render_template_string(tpl)


@automation_bp.route('/tiktok/video', methods=['GET', 'POST'])
def automation_tiktok_video():
    """Strona do uploadu wideo na TikTok Sandbox."""
    if 'tiktok_access_token' not in session:
        flash("Musisz się połączyć z TikTok przed wysłaniem wideo.", "error")
        return redirect(url_for('automation.automation_tiktok'))

    if request.method == 'POST':
        file = request.files.get('video_file')
        if not file or not file.filename:
            flash("Wybierz plik wideo (mp4 lub mov).", "error")
            return redirect(request.url)

        # przygotuj upload
        files = {'video_file': (file.filename, file.stream, file.mimetype)}
        data = {
            'open_id': session['tiktok_open_id'],
            'access_token': session['tiktok_access_token']
        }
        try:
            resp = requests.post(
                'https://open.tiktokapis.com/v2/post/publish/video/upload/',
                data=data, files=files, timeout=30
            )
            resp.raise_for_status()
        except Exception as e:
            current_app.logger.error("Upload video failed: %s", e)
            flash("Błąd podczas uploadu wideo.", "error")
            return redirect(request.url)

        result = resp.json()
        current_app.logger.debug("Upload response: %r", result)
        if result.get('code') == 0:
            flash("Wideo pomyślnie przesłane do sandboxu.", "success")
        else:
            flash(f"Sandbox zwrócił błąd: {result}", "error")

        return redirect(url_for('automation.automation_tiktok_video'))

    # GET → formularz
    tpl = '''
    <!doctype html><html lang="pl"><head><meta charset="utf-8"><title>Upload Wideo TikTok</title>
    <style>
      body{font-family:Arial,sans-serif;background:#f2f2f2;}
      .container{max-width:600px;margin:50px auto;background:#fff;padding:20px;
        border-radius:8px;box-shadow:0 2px 5px rgba(0,0,0,0.2);}
      form{margin-top:20px;}
      input[type=file]{display:block;margin-bottom:10px;}
      button{padding:8px 12px;background:#1f8ef1;color:#fff;border:none;border-radius:4px;}
      button:hover{background:#0a6db9;}
      .flash{margin:10px 0;padding:8px;border-radius:4px;}
      .flash.success{background:#dfd;color:#090;}
      .flash.error{background:#fdd;color:#900;}
    </style>
    </head><body>
      <div class="container">
        <h1>Upload Wideo</h1>
        ''' + _tiktok_nav + '''
        {% with msgs = get_flashed_messages(with_categories=true) %}
          {% for cat,msg in msgs %}
            <div class="flash {{cat}}">{{msg}}</div>
          {% endfor %}
        {% endwith %}
        <form method="post" enctype="multipart/form-data">
          <label>Wybierz plik (mp4, mov):</label>
          <input type="file" name="video_file" accept=".mp4,.mov">
          <button type="submit">Wyślij do sandbox</button>
        </form>
        <p><a href="{{ url_for('automation.automation_tiktok') }}">← Powrót</a></p>
      </div>
    </body></html>
    '''
    return render_template_string(tpl)


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
        db.session.add(new); db.session.commit()
        flash("Dodano nowy wpis.", "success")
        return redirect(url_for('automation.automation_tiktok_plan'))

    posts = ScheduledPost.query\
        .filter_by(user_id=user_id)\
        .order_by(ScheduledPost.date.asc(), ScheduledPost.time.asc())\
        .all()

    tpl = '''
    <!doctype html><html lang="pl"><head><meta charset="utf-8"><title>Plan treści TikTok</title>
    <style>body{font-family:Arial,sans-serif;padding:20px;}</style>
    </head><body>
      <h1>Plan treści TikTok</h1>
      ''' + _tiktok_nav + '''
      <ul>
        {% for p in posts %}
          <li>{{p.date}} {{p.time}} – {{p.topic}}</li>
        {% endfor %}
      </ul>
      <form method="post">
        Data: <input type="date" name="post_date"><br>
        Czas: <input type="time" name="post_time"><br>
        Tytuł: <input name="topic"><br>
        Opis: <textarea name="description"></textarea><br>
        <button type="submit">Dodaj</button>
      </form>
      <p><a href="{{ url_for('automation.automation_tiktok') }}">← Powrót</a></p>
    </body></html>
    '''
    return render_template_string(tpl, posts=posts)


@automation_bp.route('/tiktok/rodzaje')
def automation_tiktok_rodzaje():
    tpl = '''
    <!doctype html><html lang="pl"><head><meta charset="utf-8"><title>Rodzaje wideo</title></head>
    <body>
      <h1>Rodzaje wideo na TikToku</h1>
      ''' + _tiktok_nav + '''
      <p>Poradniki, Q&A, kulisy pracy itp.</p>
      <p><a href="{{ url_for('automation.automation_tiktok') }}">← Powrót</a></p>
    </body></html>
    '''
    return render_template_string(tpl)


@automation_bp.route('/tiktok/scenariusze')
def automation_tiktok_scenariusze():
    tpl = '''
    <!doctype html><html lang="pl"><head><meta charset="utf-8"><title>Scenariusze</title></head>
    <body>
      <h1>Scenariusze Postów i Wytyczne</h1>
      ''' + _tiktok_nav + '''
      <p>Przykładowe schematy i wytyczne.</p>
      <p><a href="{{ url_for('automation.automation_tiktok') }}">← Powrót</a></p>
    </body></html>
    '''
    return render_template_string(tpl)


@automation_bp.route('/tiktok/timeline')
def automation_tiktok_timeline():
    tpl = '''
    <!doctype html><html lang="pl"><head><meta charset="utf-8"><title>Timeline</title>
    <link href="https://cdn.jsdelivr.net/npm/fullcalendar@5.11.3/main.min.css" rel="stylesheet">
    <script src="https://cdn.jsdelivr.net/npm/fullcalendar@5.11.3/main.min.js"></script>
    <style>body{font-family:Arial,sans-serif;padding:20px;}#calendar{max-width:900px;margin:0 auto;}</style>
    </head><body>
      <h1>Timeline TikTok</h1>
      ''' + _tiktok_nav + '''
      <div id="calendar"></div>
      <script>
        document.addEventListener('DOMContentLoaded', function() {
          var calendarEl = document.getElementById('calendar');
          var calendar = new FullCalendar.Calendar(calendarEl, {
            initialView: 'dayGridMonth',
            locale: 'pl',
            events: [
              {% for p in posts %}
                {
                  title: '{{p.topic|escape}}',
                  start: '{{p.date}}T{{p.time}}'
                },
              {% endfor %}
            ]
          });
          calendar.render();
        });
      </script>
      <p><a href="{{ url_for('automation.automation_tiktok') }}">← Powrót</a></p>
    </body></html>
    '''
    # pobierz wpisy do kalendarza
    posts = ScheduledPost.query.filter_by(
        user_id=session.get('tiktok_open_id')
    ).all()
    return render_template_string(tpl, posts=posts)


# -------------------------------------------------
#      FACEBOOK
# -------------------------------------------------
@automation_bp.route('/facebook')
def automation_facebook():
    tpl = '''
    <!doctype html><html lang="pl"><head><meta charset="utf-8"><title>Facebook</title></head>
    <body>
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
        <!doctype html><html lang="pl"><head><meta charset="utf-8"><title>Publikuj na FB</title></head>
        <body>
          <h1>Publikuj na Facebooku</h1>
          <form method="post"><textarea name="content"></textarea><br>
          <button type="submit">Publikuj</button></form>
          <p><a href="{{ url_for('automation.automation_facebook') }}">← Powrót</a></p>
        </body></html>
        ''')
    content = request.form['content']
    publish_post_to_facebook(content)
    flash("Opublikowano na Facebooku.", "success")
    return redirect(url_for('automation.automation_facebook_publish'))
