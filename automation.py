# automation.py
from flask import Blueprint, render_template_string, url_for, request, flash, redirect, session, jsonify
from datetime import datetime
from app import db  # lub inny sposób importu instancji SQLAlchemy
from automation_models import ScheduledPost

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
            /* Prosty, kompaktowy styl */
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
    Prosta strona z nawigacją do planu treści / rodzajów wideo / scenariuszy.
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
        </style>
    </head>
    <body>
        <div class="container">
            <h1>Automatyzacja TikTok</h1>
            <nav>
                <a href="{{ url_for('automation.automation_tiktok_plan') }}">Plan treści</a> |
                <a href="{{ url_for('automation.automation_tiktok_rodzaje') }}">Rodzaje wideo</a> |
                <a href="{{ url_for('automation.automation_tiktok_scenariusze') }}">Scenariusze</a>
            </nav>
            <hr>
            <p>Tu możesz skonfigurować automatyzację i plan publikacji na TikToku.</p>
            <p><a href="{{ url_for('automation.automation_home') }}">Powrót do listy platform</a></p>
        </div>
    </body>
    </html>
    '''
    return render_template_string(tiktok_template)

@automation_bp.route('/tiktok/plan', methods=['GET', 'POST'])
def automation_tiktok_plan():
    """
    Strona planu treści: wyświetlanie, dodawanie wpisów.
    Obsługa edycji i usuwania w oddzielnych trasach.
    """
    if 'user_id' not in session:
        flash("Musisz być zalogowany, aby zarządzać planem treści.", "error")
        return redirect(url_for('login'))

    user_id = session['user_id']

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

    # Wyświetlanie postów
    scheduled_posts = ScheduledPost.query.filter_by(user_id=user_id).order_by(
        ScheduledPost.date.asc(), ScheduledPost.time.asc()
    ).all()

    plan_template = '''
    <!DOCTYPE html>
    <html lang="pl">
    <head>
      <meta charset="UTF-8">
      <title>Plan Treści (TikTok)</title>
      <style>
         body {
             font-family: Arial, sans-serif;
             background-color: #f2f2f2;
             margin: 0;
             padding: 0;
         }
         .container {
             max-width: 800px;
             margin: 20px auto;
             background-color: #fff;
             padding: 20px;
             box-shadow: 0 4px 8px rgba(0,0,0,0.1);
             position: relative;
         }
         .back-button {
             position: absolute;
             top: 10px;
             left: 10px;
             font-size: 14px;
             text-decoration: none;
             color: #fff;
             background-color: #1f8ef1;
             padding: 6px 10px;
             border-radius: 4px;
             display: inline-flex;
             align-items: center;
         }
         .back-button:hover {
             background-color: #0a6db9;
         }
         .back-button:before {
             content: "←";
             margin-right: 5px;
         }
         h1 {
             text-align: left;
             margin-bottom: 20px;
             font-size: 20px;
         }
         form {
             margin-bottom: 20px;
         }
         label {
             display: block;
             margin-top: 10px;
             font-size: 14px;
             color: #333;
         }
         input[type="date"],
         input[type="time"],
         input[type="text"],
         textarea {
             width: 100%;
             padding: 8px;
             margin-top: 5px;
             border: 1px solid #ccc;
             border-radius: 4px;
             font-size: 14px;
         }
         button.submit-btn {
             margin-top: 15px;
             padding: 10px 20px;
             background-color: #1f8ef1;
             color: #fff;
             border: none;
             border-radius: 4px;
             cursor: pointer;
             font-size: 14px;
         }
         button.submit-btn:hover {
             background-color: #0a6db9;
         }
         .post-list {
             margin-top: 30px;
         }
         .post-item {
             border-bottom: 1px solid #eee;
             padding: 10px 0;
             font-size: 14px;
         }
         .post-item:last-child {
             border-bottom: none;
         }
         .post-item strong {
             color: #1f8ef1;
         }
         .action-buttons {
             margin-top: 5px;
         }
         .action-buttons a,
         .action-buttons form {
             display: inline-block;
             margin-right: 10px;
         }
         .action-buttons a {
             color: #fff;
             background-color: #17a2b8; /* np. niebieskawy */
             padding: 5px 10px;
             border-radius: 4px;
             text-decoration: none;
             font-size: 13px;
         }
         .action-buttons a:hover {
             background-color: #138496;
         }
         .delete-btn {
             background-color: #dc3545; /* czerwony */
             color: #fff;
             border: none;
             padding: 5px 10px;
             border-radius: 4px;
             cursor: pointer;
             font-size: 13px;
         }
         .delete-btn:hover {
             background-color: #c82333;
         }
      </style>
    </head>
    <body>
      <div class="container">
         <a href="{{ url_for('automation.automation_tiktok') }}" class="back-button">back</a>
         <h1>Plan Treści dla TikToka</h1>
         <!-- Formularz dodawania nowego wpisu -->
         <form method="post">
             <label for="post_date">Data publikacji:</label>
             <input type="date" id="post_date" name="post_date" required>

             <label for="post_time">Godzina publikacji:</label>
             <input type="time" id="post_time" name="post_time" required>

             <label for="topic">Temat:</label>
             <input type="text" id="topic" name="topic" required>

             <label for="description">Opis/treść:</label>
             <textarea id="description" name="description" rows="3" required></textarea>

             <button type="submit" class="submit-btn">Dodaj wpis do harmonogramu</button>
         </form>

         <div class="post-list">
             <h2>Zaplanowane posty:</h2>
             {% for post in scheduled_posts %}
             <div class="post-item">
                 <p><strong>{{ post.topic }}</strong></p>
                 <p>{{ post.date }} o {{ post.time }}</p>
                 <p>{{ post.description }}</p>
                 <div class="action-buttons">
                     <!-- Link do edycji (GET) -->
                     <a href="{{ url_for('automation.edit_scheduled_post', post_id=post.id) }}">Edytuj</a>

                     <!-- Formularz do usuwania (POST) -->
                     <form action="{{ url_for('automation.delete_scheduled_post', post_id=post.id) }}"
                           method="post"
                           style="display:inline;">
                         <button type="submit" class="delete-btn"
                                 onclick="return confirm('Czy na pewno chcesz usunąć ten wpis?');">
                             Usuń
                         </button>
                     </form>
                 </div>
             </div>
             {% endfor %}
         </div>
      </div>
    </body>
    </html>
    '''
    return render_template_string(plan_template, scheduled_posts=scheduled_posts)

@automation_bp.route('/tiktok/plan/edit/<int:post_id>', methods=['GET', 'POST'])
def edit_scheduled_post(post_id):
    """
    Edycja istniejącego wpisu w harmonogramie.
    """
    if 'user_id' not in session:
        flash("Musisz być zalogowany, aby edytować wpisy.", "error")
        return redirect(url_for('login'))

    user_id = session['user_id']
    post = ScheduledPost.query.get_or_404(post_id)

    # Sprawdź, czy post należy do zalogowanego użytkownika
    if post.user_id != user_id:
        flash("Brak dostępu do edycji tego wpisu.", "error")
        return redirect(url_for('automation.automation_tiktok_plan'))

    if request.method == 'POST':
        # Aktualizujemy dane
        post_date_str = request.form.get('post_date')
        post_time_str = request.form.get('post_time')
        topic = request.form.get('topic')
        description = request.form.get('description')

        post.date = datetime.strptime(post_date_str, "%Y-%m-%d").date()
        post.time = datetime.strptime(post_time_str, "%H:%M").time()
        post.topic = topic
        post.description = description

        db.session.commit()
        flash("Wpis został zaktualizowany.", "success")
        return redirect(url_for('automation.automation_tiktok_plan'))

    # Jeśli GET – wyświetlamy formularz z istniejącymi danymi
    edit_template = '''
    <!DOCTYPE html>
    <html lang="pl">
    <head>
      <meta charset="UTF-8">
      <title>Edycja Wpisu</title>
      <style>
         body { font-family: Arial, sans-serif; background-color: #f2f2f2; margin: 0; padding: 0; }
         .container {
             max-width: 600px; margin: 20px auto; background-color: #fff;
             padding: 20px; box-shadow: 0 4px 8px rgba(0,0,0,0.1);
             position: relative;
         }
         .back-button {
             position: absolute; top: 10px; left: 10px;
             font-size: 14px; text-decoration: none; color: #fff;
             background-color: #1f8ef1; padding: 6px 10px; border-radius: 4px;
         }
         .back-button:hover { background-color: #0a6db9; }
         .back-button:before { content: "←"; margin-right: 5px; }
         h1 { text-align: left; margin-bottom: 20px; font-size: 20px; }
         label { display: block; margin-top: 10px; font-size: 14px; color: #333; }
         input[type="date"], input[type="time"], input[type="text"], textarea {
             width: 100%; padding: 8px; margin-top: 5px; border: 1px solid #ccc;
             border-radius: 4px; font-size: 14px;
         }
         button.submit-btn {
             margin-top: 15px; padding: 10px 20px; background-color: #28a745;
             color: #fff; border: none; border-radius: 4px; cursor: pointer; font-size: 14px;
         }
         button.submit-btn:hover { background-color: #218838; }
      </style>
    </head>
    <body>
      <div class="container">
         <a href="{{ url_for('automation.automation_tiktok_plan') }}" class="back-button">back</a>
         <h1>Edycja Wpisu</h1>
         <form method="post">
             <label for="post_date">Data publikacji:</label>
             <input type="date" id="post_date" name="post_date" value="{{ post.date }}" required>

             <label for="post_time">Godzina publikacji:</label>
             <input type="time" id="post_time" name="post_time"
                    value="{{ post.time.strftime('%H:%M') if post.time else '' }}" required>

             <label for="topic">Temat:</label>
             <input type="text" id="topic" name="topic" value="{{ post.topic }}" required>

             <label for="description">Opis/treść:</label>
             <textarea id="description" name="description" rows="3" required>{{ post.description }}</textarea>

             <button type="submit" class="submit-btn">Zapisz zmiany</button>
         </form>
      </div>
    </body>
    </html>
    '''
    return render_template_string(edit_template, post=post)

@automation_bp.route('/tiktok/plan/delete/<int:post_id>', methods=['POST'])
def delete_scheduled_post(post_id):
    """
    Usunięcie wpisu z harmonogramu.
    """
    if 'user_id' not in session:
        flash("Musisz być zalogowany, aby usuwać wpisy.", "error")
        return redirect(url_for('login'))

    user_id = session['user_id']
    post = ScheduledPost.query.get_or_404(post_id)

    if post.user_id != user_id:
        flash("Brak dostępu do usunięcia tego wpisu.", "error")
        return redirect(url_for('automation.automation_tiktok_plan'))

    db.session.delete(post)
    db.session.commit()

    flash("Wpis został usunięty.", "success")
    return redirect(url_for('automation.automation_tiktok_plan'))


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
        <h1>Scenariusze Postów i Wytyczne</h1>
        <p>Przykładowe schematy i wytyczne dotyczące doradztwa, pośrednictwa pracy, legalizacji dokumentów.</p>
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
    <head><title>Automatyzacja Facebook</title></head>
    <body>
        <h1>Automatyzacja Facebook - Placeholder</h1>
        <p>Konfiguracja automatyzacji dla Facebooka (w przyszłości).</p>
        <p><a href="{{ url_for('automation.automation_home') }}">Powrót</a></p>
    </body>
    </html>
    '''
    return render_template_string(fb_template)
