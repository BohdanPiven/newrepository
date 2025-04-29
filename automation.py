# automation.py
from flask import (
    Blueprint, render_template_string, url_for, request,
    flash, redirect, session, jsonify, get_flashed_messages
)
from datetime import datetime
from app import db
from automation_models import ScheduledPost
from selenium_facebook_post import publish_post_to_facebook

automation_bp = Blueprint('automation', __name__, url_prefix='/automation')


@automation_bp.route('/', endpoint='automation_home')
def automation_home():
    home_template = '''
    <!DOCTYPE html><html lang="pl"><head><meta charset="UTF-8">
    <title>Automation - Główna</title><style>
      *{margin:0;padding:0;box-sizing:border-box;}
      body{font-family:Arial,sans-serif;background:#f2f2f2;}
      .container{max-width:600px;margin:20px auto;background:#fff;padding:20px;
        box-shadow:0 4px 8px rgba(0,0,0,0.1);position:relative;}
      .back-button{position:absolute;top:10px;left:10px;
        font-size:14px;text-decoration:none;color:#fff;
        background:#1f8ef1;padding:6px 10px;border-radius:4px;
        display:inline-flex;align-items:center;}
      .back-button:hover{background:#0a6db9;}
      .back-button:before{content:"←";margin-right:5px;}
      .platform-list a{display:block;margin:6px 0;padding:8px 12px;
        background:#1f8ef1;color:#fff;text-decoration:none;border-radius:4px;}
      .platform-list a:hover{background:#0a6db9;}
    </style></head><body>
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
    return render_template_string(home_template)


@automation_bp.route('/tiktok')
def automation_tiktok():
    tiktok_template = '''
    <!DOCTYPE html><html lang="pl"><head><meta charset="UTF-8">
    <title>Automatyzacja TikTok</title><style>
      body{font-family:Arial,sans-serif;background:#f2f2f2;}
      .container{max-width:800px;margin:50px auto;background:#fff;
        padding:20px;border-radius:8px;box-shadow:0 2px 5px rgba(0,0,0,0.2);}
      h1{margin-bottom:10px;}
      nav a{margin:0 10px;color:#1f8ef1;text-decoration:none;}
      nav a:hover{text-decoration:underline;}
      .flash{padding:.5rem;border-radius:4px;margin-bottom:1rem;}
      .flash.success{background:#dfd;color:#090;}
      .flash.error{background:#fdd;color:#900;}
      .login-link,.logout-link{
        display:inline-block;margin-top:20px;padding:10px 15px;
        background:#1f8ef1;color:#fff;text-decoration:none;border-radius:4px;
      }
      .login-link:hover,.logout-link:hover{background:#0a6db9;}
      .user-info{margin-top:10px;color:#555;}
    </style></head><body>
      <div class="container">
        <h1>Automatyzacja TikTok</h1>

        {# pokaż tylko jedną wiadomość #}
        {% set succ = get_flashed_messages(category_filter=['success']) %}
        {% set err  = get_flashed_messages(category_filter=['error']) %}
        {% if succ %}
          <div class="flash success">{{ succ[-1] }}</div>
        {% elif err %}
          <div class="flash error">{{ err[-1] }}</div>
        {% endif %}

        {# przycisk zaloguj/wyloguj #}
        {% if session.get('tiktok_open_id') %}
          <p class="user-info">✅ Połączono jako <code>{{ session.tiktok_open_id }}</code></p>
          <a href="{{ url_for('tiktok_auth.logout') }}" class="logout-link">Wyloguj się</a>
        {% else %}
          <a href="{{ url_for('tiktok_auth.login') }}" class="login-link">Zaloguj się przez TikTok</a>
        {% endif %}

        <nav>
          <a href="{{ url_for('automation.automation_tiktok_plan') }}">Plan treści</a> |
          <a href="{{ url_for('automation.automation_tiktok_rodzaje') }}">Rodzaje wideo</a> |
          <a href="{{ url_for('automation.automation_tiktok_scenariusze') }}">Scenariusze</a> |
          <a href="{{ url_for('automation.automation_tiktok_timeline') }}">Timeline</a>
        </nav>
        <hr>
        <p>Tu możesz skonfigurować plan i automatyzację.</p>
        <p><a href="{{ url_for('automation.automation_home') }}">Powrót do listy platform</a></p>
      </div>
    </body></html>
    '''
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
        new = ScheduledPost(date=d, time=t,
                            topic=request.form['topic'],
                            description=request.form['description'],
                            user_id=user_id)
        db.session.add(new); db.session.commit()
        flash("Dodano nowy wpis.", "success")
        return redirect(url_for('automation.automation_tiktok_plan'))

    posts = ScheduledPost.query.filter_by(user_id=user_id)\
             .order_by(ScheduledPost.date, ScheduledPost.time).all()
    plan_template = '''
    <!DOCTYPE html><html lang="pl"><head><meta charset="UTF-8">
    <title>Plan treści TikTok</title></head><body>
      <h1>Plan treści TikTok</h1>
      <ul>
        {% for p in posts %}
          <li>{{ p.date }} {{ p.time }} – {{ p.topic }}</li>
        {% endfor %}
      </ul>
      <form method="post">
        <label>Data: <input type="date" name="post_date"></label><br>
        <label>Czas: <input type="time" name="post_time"></label><br>
        <label>Tytuł: <input name="topic"></label><br>
        <label>Opis: <textarea name="description"></textarea></label><br>
        <button type="submit">Dodaj</button>
      </form>
      <p><a href="{{ url_for('automation.automation_tiktok') }}">Powrót</a></p>
    </body></html>
    '''
    return render_template_string(plan_template, posts=posts)


@automation_bp.route('/tiktok/rodzaje')
def automation_tiktok_rodzaje():
    tpl = '''<!DOCTYPE html><html lang="pl"><head><meta charset="UTF-8">
    <title>Rodzaje wideo</title></head><body>
      <h1>Rodzaje wideo</h1>
      <p>Poradniki, Q&A, kulisy pracy...</p>
      <p><a href="{{ url_for('automation.automation_tiktok') }}">Powrót</a></p>
    </body></html>'''
    return render_template_string(tpl)


@automation_bp.route('/tiktok/scenariusze')
def automation_tiktok_scenariusze():
    tpl = '''<!DOCTYPE html><html lang="pl"><head><meta charset="UTF-8">
    <title>Scenariusze</title></head><body>
      <h1>Scenariusze Postów</h1>
      <p>Szablony i wytyczne...</p>
      <p><a href="{{ url_for('automation.automation_tiktok') }}">Powrót</a></p>
    </body></html>'''
    return render_template_string(tpl)


@automation_bp.route('/tiktok/timeline')
def automation_tiktok_timeline():
    tpl = '''<!DOCTYPE html><html lang="pl"><head><meta charset="UTF-8">
    <title>Timeline</title></head><body>
      <h1>Timeline (FullCalendar)</h1>
      <p>(Kalendarz z wydarzeniami)</p>
      <p><a href="{{ url_for('automation.automation_tiktok') }}">Powrót</a></p>
    </body></html>'''
    return render_template_string(tpl)


@automation_bp.route('/facebook')
def automation_facebook():
    tpl = '''<!DOCTYPE html><html lang="pl"><head><meta charset="UTF-8">
    <title>Facebook</title></head><body>
      <h1>Automatyzacja Facebook</h1>
      <p>Placeholder...</p>
      <p><a href="{{ url_for('automation.automation_home') }}">Powrót</a></p>
    </body></html>'''
    return render_template_string(tpl)


@automation_bp.route('/facebook/publish', methods=['GET','POST'])
def automation_facebook_publish():
    if request.method == 'GET':
        tpl = '''<!DOCTYPE html><html lang="pl"><head><meta charset="UTF-8">
        <title>Publikuj na FB</title></head><body>
          <h1>Publikuj na Facebooku</h1>
          <form method="post">
            <textarea name="content"></textarea><br>
            <button type="submit">Publikuj</button>
          </form>
          <p><a href="{{ url_for('automation.automation_facebook') }}">Powrót</a></p>
        </body></html>'''
        return render_template_string(tpl)
    content = request.form['content']
    publish_post_to_facebook(content)
    flash("Opublikowano na Facebooku.", "success")
    return redirect(url_for('automation.automation_facebook_publish'))
