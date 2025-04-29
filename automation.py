# automation.py  – Blueprint zarządzający automatyzacją (TikTok, Facebook, itp.)
from flask import (
    Blueprint,
    render_template_string,
    url_for,
    request,
    flash,
    redirect,
    session,
    jsonify,
    current_app,
    get_flashed_messages
)
from datetime import datetime
import os
from app import db  # import instancji SQLAlchemy z Twojego pliku głównego (app.py)
from automation_models import ScheduledPost  # Twój model zdefiniowany w automation_models.py
# ➊ – zaimportuj funkcję publikującą z Twojego pliku selenium_facebook_post.py:
from selenium_facebook_post import publish_post_to_facebook

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
        <style>
            * { margin: 0; padding: 0; box-sizing: border-box; }
            body { font-family: Arial, sans-serif; background-color: #f2f2f2; }
            .container {
                max-width: 600px;
                margin: 20px auto;
                background-color: #fff;
                padding: 20px;
                box-shadow: 0 4px 8px rgba(0,0,0,0.1);
                position: relative;
            }
            .back-button {
                position: absolute; top: 10px; left: 10px;
                font-size: 14px; text-decoration: none; color: #fff;
                background-color: #1f8ef1; padding: 6px 10px; border-radius: 4px;
                display: inline-flex; align-items: center;
            }
            .back-button:hover { background-color: #0a6db9; }
            .back-button:before { content: "←"; margin-right: 5px; }
            h1 { font-size: 20px; margin-bottom: 10px; text-align: left; }
            p { font-size: 14px; margin-bottom: 10px; text-align: left; color: #555; }
            .platform-list a {
                display: block; margin: 6px 0; padding: 8px 12px;
                background-color: #1f8ef1; color: #fff; text-decoration: none;
                border-radius: 4px; text-align: left; font-size: 14px;
            }
            .platform-list a:hover { background-color: #0a6db9; }
        </style>
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


@automation_bp.route('/tiktok')
def automation_tiktok():
    """Panel Automatyzacji TikTok"""
    tiktok_template = '''
    <!DOCTYPE html>
    <html lang="pl">
    <head>
        <meta charset="UTF-8">
        <title>Automatyzacja TikTok</title>
        <style>
            body { font-family: Arial, sans-serif; background-color: #f2f2f2; }
            .container { max-width: 800px; margin: 50px auto; background: #fff; padding: 20px; border-radius: 8px; box-shadow: 0 2px 5px rgba(0,0,0,0.2); }
            h1 { margin-bottom: 10px; }
            nav a { margin: 0 10px; text-decoration: none; color: #1f8ef1; }
            nav a:hover { text-decoration: underline; }
            .flash-container { margin-bottom: 1rem; }
            .flash.error   { background: #fdd; color: #900; padding: .5rem; border-radius: 4px; }
            .flash.success { background: #dfd; color: #090; padding: .5rem; border-radius: 4px; }
            .login-link { display: inline-block; margin-top: 20px; padding: 10px 15px; background-color: #1f8ef1; color: #fff; text-decoration: none; border-radius: 4px; }
            .login-link:hover { background-color: #0a6db9; }
            .user-info { margin-top: 10px; font-size: 14px; color: #555; }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>Automatyzacja TikTok</h1>

            {% with messages = get_flashed_messages(with_categories=true) %}
              {% if messages %}
                <div class="flash-container">
                  {% for category, msg in messages %}
                    <div class="flash {{ category }}">{{ msg }}</div>
                  {% endfor %}
                </div>
              {% endif %}
            {% endwith %}

            {% if session.get('tiktok_open_id') %}
              <p class="user-info">✅ Połączono jako: <code>{{ session.tiktok_open_id }}</code></p>
            {% endif %}

            <nav>
                <a href="{{ url_for('automation.automation_tiktok_plan') }}">Plan treści</a> |
                <a href="{{ url_for('automation.automation_tiktok_rodzaje') }}">Rodzaje wideo</a> |
                <a href="{{ url_for('automation.automation_tiktok_scenariusze') }}">Scenariusze</a> |
                <a href="{{ url_for('automation.automation_tiktok_timeline') }}">Timeline</a>
            </nav>
            <hr>
            <p>Tu możesz skonfigurować automatyzację i plan publikacji na TikToku.</p>

            <!-- Link do logowania przez TikTok -->
            <p>
              <a href="{{ url_for('tiktok_auth.login') }}" class="login-link">
                Zaloguj się przez TikTok
              </a>
            </p>

            <p><a href="{{ url_for('automation.automation_home') }}">Powrót do listy platform</a></p>
        </div>
    </body>
    </html>
    '''
    return render_template_string(tiktok_template)


@automation_bp.route('/tiktok/plan', methods=['GET', 'POST'])
def automation_tiktok_plan():
    """Plan treści TikTok"""
    if 'tiktok_open_id' not in session:
        flash("Musisz się połączyć z TikTok Sandbox.", "error")
        return redirect(url_for('automation.automation_tiktok'))
    user_id = session['tiktok_open_id']

    if request.method == 'POST':
        post_date_str = request.form.get('post_date')
        post_time_str = request.form.get('post_time')
        topic = request.form.get('topic')
        description = request.form.get('description')
        date_obj = datetime.strptime(post_date_str, "%Y-%m-%d").date()
        time_obj = datetime.strptime(post_time_str, "%H:%M").time()
        new_post = ScheduledPost(
            date=date_obj,
            time=time_obj,
            topic=topic,
            description=description,
            user_id=user_id
        )
        db.session.add(new_post)
        db.session.commit()
        flash("Nowy wpis został dodany do harmonogramu.", "success")
        return redirect(url_for('automation.automation_tiktok_plan'))

    scheduled_posts = ScheduledPost.query.filter_by(user_id=user_id).order_by(
        ScheduledPost.date.asc(), ScheduledPost.time.asc()
    ).all()
    plan_template = '''
    <!DOCTYPE html>
    <html lang="pl">
    <head><meta charset="UTF-8"><title>Plan treści TikTok</title></head>
    <body>
        <h1>Plan treści TikTok</h1>
        {% with messages = get_flashed_messages(with_categories=true) %}
          {% if messages %}
            <ul>
              {% for category,msg in messages %}
                <li class="{{ category }}">{{ msg }}</li>
              {% endfor %}
            </ul>
          {% endif %}
        {% endwith %}
        <form method="post">
            <label>Data: <input type="date" name="post_date"></label><br>
            <label>Czas: <input type="time" name="post_time"></label><br>
            <label>Tytuł: <input type="text" name="topic"></label><br>
            <label>Opis: <textarea name="description"></textarea></label><br>
            <button type="submit">Dodaj</button>
        </form>
        <h2>Zaplanowane posty</h2>
        <ul>
            {% for p in scheduled_posts %}
              <li>{{ p.date }} {{ p.time }} – {{ p.topic }}</li>
            {% endfor %}
        </ul>
        <p><a href="{{ url_for('automation.automation_tiktok') }}">Powrót</a></p>
    </body>
    </html>
    '''
    return render_template_string(plan_template, scheduled_posts=scheduled_posts)


@automation_bp.route('/tiktok/plan/edit/<int:post_id>', methods=['GET', 'POST'])
def edit_scheduled_post(post_id):
    """Edycja zaplanowanego postu"""
    post = ScheduledPost.query.get_or_404(post_id)
    if request.method == 'POST':
        post.date = datetime.strptime(request.form.get('post_date'), "%Y-%m-%d").date()
        post.time = datetime.strptime(request.form.get('post_time'), "%H:%M").time()
        post.topic = request.form.get('topic')
        post.description = request.form.get('description')
        db.session.commit()
        flash("Wpis został zaktualizowany.", "success")
        return redirect(url_for('automation.automation_tiktok_plan'))
    edit_template = '''
    <!DOCTYPE html>
    <html lang="pl">
    <head><meta charset="UTF-8"><title>Edycja postu</title></head>
    <body>
        <h1>Edytuj post</h1>
        <form method="post">
            <label>Data: <input type="date" name="post_date" value="{{ post.date }}"></label><br>
            <label>Czas: <input type="time" name="post_time" value="{{ post.time }}"></label><br>
            <label>Tytuł: <input type="text" name="topic" value="{{ post.topic }}"></label><br>
            <label>Opis: <textarea name="description">{{ post.description }}</textarea></label><br>
            <button type="submit">Zapisz zmiany</button>
        </form>
        <p><a href="{{ url_for('automation.automation_tiktok_plan') }}">Powrót</a></p>
    </body>
    </html>
    '''
    return render_template_string(edit_template, post=post)


@automation_bp.route('/tiktok/plan/delete/<int:post_id>', methods=['POST'])
def delete_scheduled_post(post_id):
    """Usuwanie zaplanowanego postu"""
    post = ScheduledPost.query.get_or_404(post_id)
    db.session.delete(post)
    db.session.commit()
    flash("Wpis został usunięty.", "success")
    return redirect(url_for('automation.automation_tiktok_plan'))


@automation_bp.route('/tiktok/timeline')
def automation_tiktok_timeline():
    """Widok kalendarza (FullCalendar)"""
    timeline_template = '''
    <!DOCTYPE html>
    <html lang="pl">
    <head><meta charset="UTF-8"><title>Timeline TikTok</title></head>
    <body>
        <h1>Timeline TikTok</h1>
        <p>(Tutaj pełny kalendarz z wydarzeniami)</p>
        <p><a href="{{ url_for('automation.automation_tiktok') }}">Powrót</a></p>
    </body>
    </html>
    '''
    return render_template_string(timeline_template)


@automation_bp.route('/tiktok/rodzaje')
def automation_tiktok_rodzaje():
    rodzaje_template = '''
    <!DOCTYPE html>
    <html lang="pl">
    <head><meta charset="UTF-8"><title>Rodzaje wideo (TikTok)</title></head>
    <body>
        <h1>Rodzaje wideo na TikToku</h1>
        <p>Krótki opis: poradniki, Q&A, kulisy pracy itp.</p>
        <p><a href="{{ url_for('automation.automation_tiktok') }}">Powrót</a></p>
    </body>
    </html>
    '''
    return render_template_string(rodzaje_template)


@automation_bp.route('/tiktok/scenariusze')
def automation_tiktok_scenariusze():
    scenariusze_template = '''
    <!DOCTYPE html>
    <html lang="pl">
    <head><meta charset="UTF-8"><title>Scenariusze Postów (TikTok)</title></head>
    <body>
        <h1>Scenariusze Postów i Wytyczne</title>
        <p>Przykładowe schematy i wytyczne.</p>
        <p><a href="{{ url_for('automation.automation_tiktok') }}">Powrót</a></p>
    </body>
    </html>
    '''
    return render_template_string(scenariusze_template)


@automation_bp.route('/facebook')
def automation_facebook():
    fb_template = '''
    <!DOCTYPE html>
    <html lang="pl">
    <head><meta charset="UTF-8"><title>Automatyzacja Facebook</title></head>
    <body>
        <h1>Automatyzacja Facebook - Placeholder</title>
        <p>Konfiguracja automatyzacji dla Facebooka.</p>
        <p><a href="{{ url_for('automation.automation_home') }}">Powrót</a></p>
    </body>
    </html>
    '''
    return render_template_string(fb_template)


@automation_bp.route('/facebook/publish', methods=['GET', 'POST'])
def automation_facebook_publish():
    """Publikacja postu na Facebooku przez Selenium"""
    if request.method == 'GET':
        form_template = '''
        <!DOCTYPE html>
        <html lang="pl">
        <head><meta charset="UTF-8"><title>Publikuj na Facebooku</title></head>
        <body>
            <h1>Publikuj na Facebooku</h1>
            <form method="post">
                <label>Treść: <textarea name="content"></textarea></label><br>
                <button type="submit">Publikuj teraz</button>
            </form>
            <p><a href="{{ url_for('automation.automation_facebook') }}">Powrót</a></p>
        </body>
        </html>
        '''
        return render_template_string(form_template)
    content = request.form.get('content')
    publish_post_to_facebook(content)
    flash("Post został opublikowany na Facebooku.", "success")
    return redirect(url_for('automation.automation_facebook_publish'))
