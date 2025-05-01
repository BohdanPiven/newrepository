# automation.py
import requests
import logging
from flask import (
    Blueprint,
    render_template_string,
    url_for,
    request,
    flash,
    redirect,
    session,
    jsonify,
    get_flashed_messages,
    current_app
)
from datetime import datetime
from app import db
from automation_models import ScheduledPost
from selenium_facebook_post import publish_post_to_facebook
from tiktok_auth import UPLOAD_VIDEO_URL

automation_bp = Blueprint('automation', __name__, url_prefix='/automation')

# Ustaw logowanie INFO, żeby widzieć nasze "[TikTok upload]" w heroku logs
logging.getLogger('werkzeug').setLevel(logging.INFO)


@automation_bp.route('/', endpoint='automation_home')
def automation_home():
    tpl = '''
    <!DOCTYPE html><html lang="pl"><head><meta charset="UTF-8"><title>Panel Automatyzacji</title></head>
    <body>
      <h1>Panel Automatyzacji</h1>
      <ul>
        <li><a href="{{ url_for('automation.automation_tiktok') }}">TikTok</a></li>
        <li><a href="{{ url_for('automation.automation_facebook') }}">Facebook</a></li>
      </ul>
    </body></html>
    '''
    return render_template_string(tpl)


@automation_bp.route('/tiktok')
def automation_tiktok():
    tpl = '''
    <!DOCTYPE html><html lang="pl"><head><meta charset="UTF-8"><title>Automatyzacja TikTok</title></head>
    <body>
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
        <p><a href="{{ url_for('tiktok_auth.logout') }}">Wyloguj się</a></p>
      {% else %}
        <p><a href="{{ url_for('tiktok_auth.login') }}">Zaloguj się przez TikTok</a></p>
      {% endif %}
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
        db.session.add(new)
        db.session.commit()
        flash("Dodano wpis.", "success")
        return redirect(url_for('automation.automation_tiktok_plan'))

    posts = (ScheduledPost.query
             .filter_by(user_id=uid)
             .order_by(ScheduledPost.date.asc(), ScheduledPost.time.asc())
             .all())
    tpl = '''
    <!DOCTYPE html><html lang="pl"><head><meta charset="UTF-8"><title>Plan treści TikTok</title></head>
    <body>
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
    </body></html>
    '''
    return render_template_string(tpl, posts=posts)


@automation_bp.route('/tiktok/events')
def tiktok_events():
    uid = session.get('tiktok_open_id')
    if not uid:
        return jsonify([])
    evts = [{
        "title": p.topic,
        "start": f"{p.date.isoformat()}T{p.time.strftime('%H:%M:%S')}",
        "url": url_for('automation.automation_tiktok_plan')
    } for p in ScheduledPost.query.filter_by(user_id=uid)]
    return jsonify(evts)


@automation_bp.route('/tiktok/timeline')
def automation_tiktok_timeline():
    tpl = '''
    <!DOCTYPE html><html lang="pl"><head><meta charset="UTF-8"><title>Timeline TikTok</title>
      <link href="https://cdn.jsdelivr.net/npm/fullcalendar@6.1.8/index.global.min.css" rel="stylesheet">
    </head><body>
      <h1>Timeline TikTok</h1>
      <div id="calendar"></div>
      <p><a href="{{ url_for('automation.automation_tiktok') }}">← Powrót</a></p>
      <script src="https://cdn.jsdelivr.net/npm/fullcalendar@6.1.8/index.global.min.js"></script>
      <script>
        document.addEventListener('DOMContentLoaded', function() {
          new FullCalendar.Calendar(
            document.getElementById('calendar'),
            { initialView:'dayGridMonth', locale:'pl', events:'{{ url_for("automation.tiktok_events") }}' }
          ).render();
        });
      </script>
    </body></html>
    '''
    return render_template_string(tpl)


@automation_bp.route('/tiktok/rodzaje')
def automation_tiktok_rodzaje():
    tpl = '''
    <!DOCTYPE html><html lang="pl"><head><meta charset="UTF-8"><title>Rodzaje wideo</title></head>
    <body>
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
    <body>
      <h1>Scenariusze Postów i Wytyczne</h1>
      <p>Przykładowe schematy i wytyczne.</p>
      <p><a href="{{ url_for('automation.automation_tiktok') }}">← Powrót</a></p>
    </body></html>
    '''
    return render_template_string(tpl)


@automation_bp.route('/tiktok/video', methods=['GET','POST'])
def automation_tiktok_video():
    # … walidacja sesji …
    if request.method == 'POST':
        f = request.files['video_file']
        headers = {'Authorization': f"Bearer {session['tiktok_access_token']}"}
        init_payload = {
            "open_id": session['tiktok_open_id'],
            "upload_type": "UPLOAD_BY_FILE",
            "file_name": f.filename,
            "file_size": len(f.read())
        }
        f.stream.seek(0)  # cofnij czytanie po wyliczeniu rozmiaru

        # 1) INIT
        r1 = requests.post(VIDEO_INIT_URL, headers=headers, json=init_payload)
        r1.raise_for_status()
        data = r1.json()['data']
        upload_address = data['upload_address']
        video_id       = data['video_id']

        # 2) UPLOAD
        files = {'file': (f.filename, f.read(), 'application/octet-stream')}
        f.stream.seek(0)
        r2 = requests.post(upload_address, files=files)
        r2.raise_for_status()

        # 3) PUBLISH
        publish_payload = {
            "open_id": session['tiktok_open_id'],
            "video_id": video_id
        }
        r3 = requests.post(UPLOAD_VIDEO_URL, headers=headers, json=publish_payload)
        r3.raise_for_status()

        flash("Wideo wysłano i opublikowano pomyślnie.", "success")
        return redirect(url_for('automation.automation_tiktok_video'))


@automation_bp.route('/facebook')
def automation_facebook():
    tpl = '''
    <!DOCTYPE html><html lang="pl"><head><meta charset="UTF-8"><title>Facebook</title></head>
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
          <!DOCTYPE html><html lang="pl"><head><meta charset="UTF-8"><title>Publish FB</title></head>
          <body>
            <h1>Publikuj na Facebooku</h1>
            <form method="post">
              <textarea name="content"></textarea><br>
              <button type="submit">Publikuj</button>
            </form>
            <p><a href="{{ url_for('automation.automation_facebook') }}">← Powrót</a></p>
          </body></html>
        ''')
    publish_post_to_facebook(request.form['content'])
    flash("Opublikowano na Facebooku.", "success")
    return redirect(url_for('automation.automation_facebook'))
