from flask import (
    Blueprint,
    render_template_string,
    url_for,
    request,
    flash,
    redirect,
    session,
    get_flashed_messages
)
from datetime import datetime
from app import db
from automation_models import ScheduledPost
from selenium_facebook_post import publish_post_to_facebook

automation_bp = Blueprint('automation', __name__, url_prefix='/automation')


@automation_bp.route('/', endpoint='automation_home')
def automation_home():
    html = """
    <h1>Panel Automatyzacji</h1>
    <p><a href="{{ url_for('automation.automation_tiktok') }}">TikTok</a></p>
    <p><a href="{{ url_for('automation.automation_facebook') }}">Facebook</a></p>
    """
    return render_template_string(html)


@automation_bp.route('/tiktok')
def automation_tiktok():
    html = '''
    <h1>Automatyzacja TikTok</h1>

    {%- set S = get_flashed_messages(category_filter=['success']) %}
    {%- set E = get_flashed_messages(category_filter=['error']) %}
    {% if S %}
      <div style="background:#dfd;padding:1em;">{{ S[-1] }}</div>
    {% elif E %}
      <div style="background:#fdd;padding:1em;">{{ E[-1] }}</div>
    {% endif %}

    {% if session.get('tiktok_open_id') %}
      <p>✅ Połączono jako {{ session.tiktok_open_id }}</p>
      <p><a href="{{ url_for('tiktok_auth.logout') }}">Wyloguj się</a></p>
    {% else %}
      <p><a href="{{ url_for('tiktok_auth.login') }}">Zaloguj się przez TikTok</a></p>
    {% endif %}

    <nav>
      <a href="{{ url_for('automation.automation_tiktok_plan') }}">Plan treści</a> |
      <a href="{{ url_for('automation.automation_tiktok_rodzaje') }}">Rodzaje wideo</a> |
      <a href="{{ url_for('automation.automation_tiktok_scenariusze') }}">Scenariusze</a> |
      <a href="{{ url_for('automation.automation_tiktok_timeline') }}">Timeline</a>
    </nav>
    '''
    return render_template_string(html)


@automation_bp.route('/tiktok/plan', methods=['GET','POST'])
def automation_tiktok_plan():
    if 'tiktok_open_id' not in session:
        flash("Musisz się połączyć z TikTok.", "error")
        return redirect(url_for('automation.automation_tiktok'))

    user = session['tiktok_open_id']
    if request.method == 'POST':
        d = datetime.strptime(request.form['post_date'], "%Y-%m-%d").date()
        t = datetime.strptime(request.form['post_time'], "%H:%M").time()
        p = ScheduledPost(
            date=d,
            time=t,
            topic=request.form['topic'],
            description=request.form['description'],
            user_id=user
        )
        db.session.add(p)
        db.session.commit()
        flash("Dodano wpis.", "success")
        return redirect(url_for('automation.automation_tiktok_plan'))

    posts = ScheduledPost.query.filter_by(user_id=user).order_by(
        ScheduledPost.date, ScheduledPost.time
    ).all()
    html = """
    <h1>Plan treści</h1>
    <ul>
    {% for p in posts %}
      <li>{{ p.date }} {{ p.time }} – {{ p.topic }}</li>
    {% endfor %}
    </ul>
    <form method="post">
      Data: <input type="date" name="post_date"><br>
      Czas: <input type="time" name="post_time"><br>
      Tytuł: <input name="topic"><br>
      Opis: <textarea name="description"></textarea><br>
      <button>Dodaj</button>
    </form>
    <p><a href="{{ url_for('automation.automation_tiktok') }}">← Powrót</a></p>
    """
    return render_template_string(html, posts=posts)


@automation_bp.route('/tiktok/rodzaje')
def automation_tiktok_rodzaje():
    return render_template_string("""
    <h1>Rodzaje wideo</h1>
    <p>Poradniki, Q&A, kulisy...</p>
    <p><a href="{{ url_for('automation.automation_tiktok') }}">← Powrót</a></p>
    """)


@automation_bp.route('/tiktok/scenariusze')
def automation_tiktok_scenariusze():
    return render_template_string("""
    <h1>Scenariusze</h1>
    <p>Szablony itd.</p>
    <p><a href="{{ url_for('automation.automation_tiktok') }}">← Powrót</a></p>
    """)


@automation_bp.route('/tiktok/timeline')
def automation_tiktok_timeline():
    return render_template_string("""
    <h1>Timeline</h1>
    <p>Kalendarz wydarzeń</p>
    <p><a href="{{ url_for('automation.automation_tiktok') }}">← Powrót</a></p>
    """)


@automation_bp.route('/facebook')
def automation_facebook():
    return render_template_string("""
    <h1>Automatyzacja Facebook</h1>
    <p>Placeholder</p>
    <p><a href="{{ url_for('automation.automation_home') }}">← Powrót</a></p>
    """)


@automation_bp.route('/facebook/publish', methods=['GET','POST'])
def automation_facebook_publish():
    if request.method=='GET':
        return render_template_string("""
        <h1>Publikuj na Facebooku</h1>
        <form method="post">
          <textarea name="content"></textarea><br>
          <button>Publikuj</button>
        </form>
        <p><a href="{{ url_for('automation.automation_facebook') }}">← Powrót</a></p>
        """)
    publish_post_to_facebook(request.form['content'])
    flash("Opublikowano na Facebooku.", "success")
    return redirect(url_for('automation.automation_facebook_publish'))
