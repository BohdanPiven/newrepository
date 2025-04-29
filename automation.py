# automation.py  – Blueprint zarządzający automatyzacją (TikTok, Facebook, itp.)

from flask import (
    Blueprint,
    render_template_string,
    url_for,
    request,
    flash,
    redirect,
    session
)
from datetime import datetime
from app import db  # instancja SQLAlchemy z app.py
from automation_models import ScheduledPost  # Twój model ScheduledPost
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
    """
    Główne okno automatyzacji TikTok.
    """
    tiktok_template = '''
    <!DOCTYPE html>
    <html lang="pl">
    <head>
        <meta charset="UTF-8">
        <title>Automatyzacja TikTok</title>
        <style>
            body { font-family: Arial, sans-serif; background-color: #f2f2f2; }
            .container {
                max-width: 800px; margin: 50px auto; background: #fff;
                padding: 20px; border-radius: 8px;
                box-shadow: 0 2px 5px rgba(0,0,0,0.2);
            }
            h1 { margin-bottom: 20px; }
            nav a {
                margin: 0 10px; text-decoration: none; color: #1f8ef1;
            }
            nav a:hover { text-decoration: underline; }
            .login-link {
                display: inline-block;
                margin-top: 20px;
                padding: 10px 15px;
                background-color: #1f8ef1;
                color: #fff;
                text-decoration: none;
                border-radius: 4px;
            }
            .login-link:hover {
                background-color: #0a6db9;
            }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>Automatyzacja TikTok</h1>
            <nav>
                <a href="{{ url_for('automation.automation_tiktok_plan') }}">Plan treści</a> |
                <a href="{{ url_for('automation.automation_tiktok_rodzaje') }}">Rodzaje wideo</a> |
                <a href="{{ url_for('automation.automation_tiktok_scenariusze') }}">Scenariusze</a> |
                <a href="{{ url_for('automation.automation_tiktok_timeline') }}">Timeline</a>
            </nav>
            <hr>
            <p>Tu możesz skonfigurować automatyzację i plan publikacji na TikToku.</p>
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
    """
    Zarządzanie planem treści dla zalogowanego konta TikTok (tiktok_open_id).
    """
    if 'tiktok_open_id' not in session:
        flash("Musisz być połączony z TikTok Sandbox.", "error")
        return redirect(url_for('automation.automation_tiktok'))

    user_id = session['tiktok_open_id']  # to jest STRING, pasuje do kolumny VARCHAR

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
    <head>
        <meta charset="UTF-8">
        <title>Plan treści TikTok</title>
        <style>
            body { font-family: Arial, sans-serif; background: #f9f9f9; padding: 20px; }
            h1 { margin-bottom: 15px; }
            ul { list-style: none; padding-left: 0; }
            ul li { margin-bottom: 8px; }
            form { margin-top: 20px; }
            label { display: block; margin-bottom: 8px; }
            input, textarea { width: 100%; max-width: 400px; padding: 6px; margin-top: 4px; }
            button { padding: 8px 12px; background: #1f8ef1; color: #fff; border: none; border-radius: 4px; }
            button:hover { background: #0a6db9; }
        </style>
    </head>
    <body>
        <h1>Plan treści TikTok</h1>
        <ul>
            {% for p in scheduled_posts %}
              <li>{{ p.date }} {{ p.time }} – {{ p.topic }}</li>
            {% else %}
              <li>Brak zaplanowanych wpisów.</li>
            {% endfor %}
        </ul>
        <form method="post">
            <label>Data:
                <input type="date" name="post_date" required>
            </label>
            <label>Czas:
                <input type="time" name="post_time" required>
            </label>
            <label>Tytuł:
                <input type="text" name="topic" required>
            </label>
            <label>Opis:
                <textarea name="description" required></textarea>
            </label>
            <button type="submit">Dodaj</button>
        </form>
        <p><a href="{{ url_for('automation.automation_tiktok') }}">← Powrót</a></p>
    </body>
    </html>
    '''
    return render_template_string(plan_template, scheduled_posts=scheduled_posts)


@automation_bp.route('/tiktok/rodzaje')
def automation_tiktok_rodzaje():
    rodzaje_template = '''
    <!DOCTYPE html>
    <html lang="pl">
    <head><meta charset="UTF-8"><title>Rodzaje wideo (TikTok)</title></head>
    <body>
        <h1>Rodzaje wideo na TikToku</h1>
        <p>Poradniki, Q&A, kulisy pracy itp.</p>
        <p><a href="{{ url_for('automation.automation_tiktok') }}">← Powrót</a></p>
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
        <h1>Scenariusze Postów i Wytyczne</h1>
        <p>Przykładowe schematy i wytyczne.</p>
        <p><a href="{{ url_for('automation.automation_tiktok') }}">← Powrót</a></p>
    </body>
    </html>
    '''
    return render_template_string(scenariusze_template)


@automation_bp.route('/tiktok/timeline')
def automation_tiktok_timeline():
    timeline_template = '''
    <!DOCTYPE html>
    <html lang="pl">
    <head><meta charset="UTF-8"><title>Timeline TikTok</title></head>
    <body>
        <h1>Timeline TikTok</h1>
        <p>(Tutaj pełny kalendarz z wydarzeniami – FullCalendar)</p>
        <p><a href="{{ url_for('automation.automation_tiktok') }}">← Powrót</a></p>
    </body>
    </html>
    '''
    return render_template_string(timeline_template)


@automation_bp.route('/facebook')
def automation_facebook():
    fb_template = '''
    <!DOCTYPE html>
    <html lang="pl">
    <head><meta charset="UTF-8"><title>Automatyzacja Facebook</title></head>
    <body>
        <h1>Automatyzacja Facebook</h1>
        <p>Placeholder konfiguracji dla Facebooka.</p>
        <p><a href="{{ url_for('automation.automation_home') }}">← Powrót</a></p>
    </body>
    </html>
    '''
    return render_template_string(fb_template)


@automation_bp.route('/facebook/publish', methods=['GET', 'POST'])
def automation_facebook_publish():
    """
    Prosta publikacja na Facebooku przez Selenium.
    """
    if request.method == 'GET':
        form_template = '''
        <!DOCTYPE html>
        <html lang="pl">
        <head><meta charset="UTF-8"><title>Publikuj na Facebooku</title></head>
        <body>
            <h1>Publikuj na Facebooku</h1>
            <form method="post">
                <label>Treść:<br>
                    <textarea name="content" required></textarea>
                </label><br><br>
                <button type="submit">Publikuj teraz</button>
            </form>
            <p><a href="{{ url_for('automation.automation_facebook') }}">← Powrót</a></p>
        </body>
        </html>
        '''
        return render_template_string(form_template)

    # POST – publikujemy treść
    content = request.form.get('content')
    publish_post_to_facebook(content)
    flash("Post został opublikowany na Facebooku.", "success")
    return redirect(url_for('automation.automation_facebook_publish'))
