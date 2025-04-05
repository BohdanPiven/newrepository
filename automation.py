# automation.py
from flask import Blueprint, render_template_string, url_for, request, flash, redirect, session
from datetime import datetime, date, time
from automation_models import db, ScheduledPost

automation_bp = Blueprint('automation', __name__, url_prefix='/automation')

@automation_bp.route('/', endpoint='automation_home')
def automation_home():
    automation_home_template = '''
    <!DOCTYPE html>
    <html lang="pl">
    <head>
        <meta charset="UTF-8">
        <title>Automation - Główna</title>
        <style>
            /* Resetowanie marginesów i paddingu */
            * {
                margin: 0;
                padding: 0;
                box-sizing: border-box;
            }
            body {
                font-family: Arial, sans-serif;
                background-color: #f2f2f2;
            }
            .container {
                max-width: 600px;
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
                font-size: 20px;
                margin-bottom: 10px;
                text-align: left;
            }
            p {
                font-size: 14px;
                margin-bottom: 10px;
                text-align: left;
                color: #555;
            }
            .platform-list a {
                display: block;
                margin: 6px 0;
                padding: 8px 12px;
                background-color: #1f8ef1;
                color: #fff;
                text-decoration: none;
                border-radius: 4px;
                text-align: left;
                font-size: 14px;
            }
            .platform-list a:hover {
                background-color: #0a6db9;
            }
        </style>
    </head>
    <body>
        <div class="container">
            <!-- Przyciski powrotu -->
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
    return render_template_string(automation_home_template)


@automation_bp.route('/tiktok')
def automation_tiktok():
    tiktok_template = '''
    <!DOCTYPE html>
    <html lang="pl">
    <head>
        <meta charset="UTF-8">
        <title>Automation - TikTok</title>
        <style>
            body { font-family: Arial, sans-serif; background-color: #f2f2f2; }
            .container {
                max-width: 800px;
                margin: 50px auto;
                background: #fff;
                padding: 20px;
                border-radius: 8px;
                box-shadow: 0 2px 5px rgba(0,0,0,0.2);
            }
            h1 { margin-bottom: 20px; }
            nav a {
                margin: 0 10px;
                text-decoration: none;
                color: #1f8ef1;
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
    # Importujemy model ScheduledPost oraz instancję db z automation_models.py
    from automation_models import ScheduledPost, db

    # Sprawdź, czy użytkownik jest zalogowany
    if 'user_id' not in session:
        flash("Musisz być zalogowany, aby zarządzać planem treści.", "error")
        return redirect(url_for('login'))

    user_id = session['user_id']

    if request.method == 'POST':
        post_date_str = request.form.get('post_date')
        post_time_str = request.form.get('post_time')
        topic = request.form.get('topic')
        description = request.form.get('description')

        # Konwersja ciągów znaków na obiekty date i time
        date_obj = datetime.strptime(post_date_str, "%Y-%m-%d").date()
        time_obj = datetime.strptime(post_time_str, "%H:%M").time()

        # Tworzymy nowy obiekt ScheduledPost i zapisujemy go do bazy
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

    # Pobieramy zaplanowane posty dla danego użytkownika
    scheduled_posts = ScheduledPost.query.filter_by(user_id=user_id).order_by(
        ScheduledPost.date.asc(), ScheduledPost.time.asc()
    ).all()

    # Szablon HTML strony planu treści
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
      </style>
    </head>
    <body>
      <div class="container">
         <a href="{{ url_for('automation.automation_tiktok') }}" class="back-button">back</a>
         <h1>Plan Treści dla TikToka</h1>
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
                 <!-- Tutaj można dodać przyciski edycji/usuwania wpisu (opcjonalnie) -->
             </div>
             {% endfor %}
         </div>
      </div>
    </body>
    </html>
    '''
    return render_template_string(plan_template, scheduled_posts=scheduled_posts)



@automation_bp.route('/tiktok/plan/delete_ajax', methods=['POST'])
def delete_scheduled_post_ajax():
    from automation_models import ScheduledPost, db
    # Upewnij się, że mamy importowane jsonify – można go też dodać na górze pliku
    from flask import jsonify
    if 'user_id' not in session:
        return jsonify({"success": False, "message": "Musisz być zalogowany."}), 401
    
    user_id = session['user_id']
    data = request.get_json()
    post_id = data.get('post_id')
    if not post_id:
        return jsonify({"success": False, "message": "Brak ID wpisu (post_id)."}), 400

    scheduled_post = ScheduledPost.query.get(post_id)
    if not scheduled_post or scheduled_post.user_id != user_id:
        return jsonify({"success": False, "message": "Wpis nie istnieje lub brak dostępu."}), 403

    db.session.delete(scheduled_post)
    db.session.commit()

    return jsonify({"success": True, "message": "Wpis usunięty."}), 200



@automation_bp.route('/tiktok/rodzaje')
def automation_tiktok_rodzaje():
    rodzaje_template = '''
    <!DOCTYPE html>
    <html lang="pl">
    <head>
      <meta charset="UTF-8">
      <title>Rodzaje wideo (TikTok)</title>
      <style>
         body { 
             font-family: Arial, sans-serif; 
             background-color: #f2f2f2; 
             margin: 0; 
             padding: 0; 
         }
         .container {
             max-width: 800px;
             margin: 0 auto;
             background-color: #fff;
             padding: 40px;
             box-shadow: 0 4px 8px rgba(0,0,0,0.1);
             position: relative;
         }
         .back-button {
             position: absolute;
             top: 20px;
             left: 20px;
             font-size: 16px;
             text-decoration: none;
             color: #fff;
             background-color: #1f8ef1;
             padding: 8px 12px;
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
             margin-bottom: 30px;
         }
         p {
             text-align: left;
             margin-bottom: 20px;
         }
      </style>
    </head>
    <body>
      <div class="container">
         <a href="{{ url_for('automation.automation_tiktok') }}" class="back-button">back</a>
         <h1>Rodzaje wideo na TikToku</h1>
         <p>Przykłady formatów: krótkie poradniki, Q&A, kulisy pracy itp.</p>
      </div>
    </body>
    </html>
    '''
    return render_template_string(rodzaje_template)


@automation_bp.route('/tiktok/scenariusze')
def automation_tiktok_scenariusze():
    scenariusze_template = '''
    <!DOCTYPE html>
    <html lang="pl">
    <head>
      <meta charset="UTF-8">
      <title>Scenariusze Postów (TikTok)</title>
      <style>
         body { 
             font-family: Arial, sans-serif; 
             background-color: #f2f2f2; 
             margin: 0; 
             padding: 0; 
         }
         .container {
             max-width: 800px;
             margin: 0 auto;
             background-color: #fff;
             padding: 40px;
             box-shadow: 0 4px 8px rgba(0,0,0,0.1);
             position: relative;
         }
         .back-button {
             position: absolute;
             top: 20px;
             left: 20px;
             font-size: 16px;
             text-decoration: none;
             color: #fff;
             background-color: #1f8ef1;
             padding: 8px 12px;
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
             margin-bottom: 30px;
         }
         p {
             text-align: left;
             margin-bottom: 20px;
         }
      </style>
    </head>
    <body>
      <div class="container">
         <a href="{{ url_for('automation.automation_tiktok') }}" class="back-button">back</a>
         <h1>Scenariusze Postów i Wytyczne</h1>
         <p>Przykładowe schematy postów i wytyczne dotyczące doradztwa, pośrednictwa pracy oraz legalizacji dokumentów.</p>
      </div>
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
        <p>Tutaj w przyszłości możesz dodać konfigurację dla Facebooka.</p>
        <p><a href="{{ url_for('automation.automation_home') }}">Powrót do listy platform</a></p>
    </body>
    </html>
    '''
    return render_template_string(fb_template)
