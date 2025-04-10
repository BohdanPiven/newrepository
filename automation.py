from flask import Blueprint, render_template_string, url_for, request, flash, redirect, session, jsonify
from datetime import datetime
import os  # Potrzebne do obsługi plików
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
            
            <!-- DODAJ LINK DO LOGOWANIA PRZEZ TIKTOK: -->
            <p>
              <a href="{{ url_for('tiktok_auth.tiktok_login') }}" class="login-link">
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
    Widok harmonogramu – umożliwia dodawanie nowych wpisów oraz wyświetlanie zaplanowanych postów.
    """
    if 'user_id' not in session:
        flash("Musisz być zalogowany, aby zarządzać planem treści.", "error")
        return redirect(url_for('login'))

    user_id = session['user_id']

    if request.method == 'POST':
        # Pobieramy dane z formularza
        post_date_str = request.form.get('post_date')
        post_time_str = request.form.get('post_time')
        topic = request.form.get('topic')
        description = request.form.get('description')

        # Konwersja ciągów znaków na obiekty date/time
        date_obj = datetime.strptime(post_date_str, "%Y-%m-%d").date()
        time_obj = datetime.strptime(post_time_str, "%H:%M").time()

        # Tworzymy nowy wpis i zapisujemy go do bazy
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

    # Pobieramy zaplanowane posty dla zalogowanego użytkownika
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
         .back-button:hover { background-color: #0a6db9; }
         .back-button:before { content: "←"; margin-right: 5px; }
         h1 { text-align: left; margin-bottom: 20px; font-size: 20px; }
         form { margin-bottom: 20px; }
         label { display: block; margin-top: 10px; font-size: 14px; color: #333; }
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
         button.submit-btn:hover { background-color: #0a6db9; }
         .post-list { margin-top: 30px; }
         .post-item { border-bottom: 1px solid #eee; padding: 10px 0; font-size: 14px; }
         .post-item:last-child { border-bottom: none; }
         .post-item strong { color: #1f8ef1; }
         .action-buttons { margin-top: 5px; }
         .action-buttons a,
         .action-buttons form {
             display: inline-block;
             margin-right: 10px;
         }
         .action-buttons a {
             color: #fff;
             background-color: #17a2b8;
             padding: 5px 10px;
             border-radius: 4px;
             text-decoration: none;
             font-size: 13px;
         }
         .action-buttons a:hover { background-color: #138496; }
         .delete-btn {
             background-color: #dc3545;
             color: #fff;
             border: none;
             padding: 5px 10px;
             border-radius: 4px;
             cursor: pointer;
             font-size: 13px;
         }
         .delete-btn:hover { background-color: #c82333; }
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
                 <div class="action-buttons">
                     <a href="{{ url_for('automation.edit_scheduled_post', post_id=post.id) }}">Edytuj</a>
                     <form action="{{ url_for('automation.delete_scheduled_post', post_id=post.id) }}" method="post" style="display:inline;" onsubmit="return confirm('Czy na pewno chcesz usunąć ten wpis?');">
                         <button type="submit" class="delete-btn">Usuń</button>
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
    Umożliwia edycję istniejącego wpisu w harmonogramie.
    """
    if 'user_id' not in session:
        flash("Musisz być zalogowany, aby edytować wpisy.", "error")
        return redirect(url_for('login'))

    user_id = session['user_id']
    post = ScheduledPost.query.get_or_404(post_id)

    if post.user_id != user_id:
        flash("Brak dostępu do edycji tego wpisu.", "error")
        return redirect(url_for('automation.automation_tiktok_plan'))

    if request.method == 'POST':
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

    edit_template = '''
    <!DOCTYPE html>
    <html lang="pl">
    <head>
      <meta charset="UTF-8">
      <title>Edycja Wpisu</title>
      <style>
         body { font-family: Arial, sans-serif; background-color: #f2f2f2; margin: 0; padding: 0; }
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
         }
         .back-button:hover { background-color: #0a6db9; }
         .back-button:before { content: "←"; margin-right: 5px; }
         h1 { text-align: left; margin-bottom: 20px; font-size: 20px; }
         label { display: block; margin-top: 10px; font-size: 14px; color: #333; }
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
             background-color: #28a745;
             color: #fff;
             border: none;
             border-radius: 4px;
             cursor: pointer;
             font-size: 14px;
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
    Usuwa wpis z harmonogramu.
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


@automation_bp.route('/tiktok/timeline')
def automation_tiktok_timeline():
    """
    Wizualizacja harmonogramu przy użyciu FullCalendar.
    """
    if 'user_id' not in session:
        flash("Musisz być zalogowany, aby przeglądać harmonogram.", "error")
        return redirect(url_for('login'))
    
    user_id = session['user_id']
    scheduled_posts = ScheduledPost.query.filter_by(user_id=user_id).order_by(
        ScheduledPost.date.asc(), ScheduledPost.time.asc()
    ).all()

    # Przygotowujemy dane dla FullCalendar – każdy post to zdarzenie
    events = []
    for post in scheduled_posts:
        from datetime import datetime
        event_start = datetime.combine(post.date, post.time).isoformat()
        events.append({
            'title': post.topic,
            'start': event_start,
            'description': post.description,
        })

    timeline_template = '''
    <!DOCTYPE html>
    <html lang="pl">
    <head>
      <meta charset="UTF-8">
      <title>Timeline - Plan Treści dla TikToka</title>
      <!-- FullCalendar z CDN -->
      <link href="https://cdn.jsdelivr.net/npm/fullcalendar@6.1.8/index.global.min.css" rel="stylesheet">
      <script src="https://cdn.jsdelivr.net/npm/fullcalendar@6.1.8/index.global.min.js"></script>
      <style>
         body {
             font-family: Arial, sans-serif;
             background-color: #f2f2f2;
             margin: 20px;
             padding: 0;
         }
         #calendar {
             max-width: 900px;
             margin: 0 auto;
         }
         .back-button {
             display: inline-block;
             margin-bottom: 20px;
             text-decoration: none;
             background-color: #1f8ef1;
             color: #fff;
             padding: 6px 10px;
             border-radius: 4px;
         }
         .back-button:hover {
             background-color: #0a6db9;
         }
      </style>
    </head>
    <body>
      <a href="{{ url_for('automation.automation_tiktok') }}" class="back-button">← Back</a>
      <h1>Timeline - Plan Treści dla TikToka</h1>
      <div id="calendar"></div>
      <script>
        document.addEventListener('DOMContentLoaded', function() {
            var calendarEl = document.getElementById('calendar');
            var calendar = new FullCalendar.Calendar(calendarEl, {
              initialView: 'dayGridMonth',
              headerToolbar: {
                left: 'prev,next today',
                center: 'title',
                right: 'dayGridMonth,timeGridWeek,timeGridDay'
              },
              events: {{ events|tojson }},
              eventClick: function(info) {
                // Wyświetlenie alertu z informacjami o wpisie
                alert('Temat: ' + info.event.title + '\\nOpis: ' + info.event.extendedProps.description);
              }
            });
            calendar.render();
        });
      </script>
    </body>
    </html>
    '''
    return render_template_string(timeline_template, events=events)


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

@automation_bp.route('/facebook/publish', methods=['GET', 'POST'])
def automation_facebook_publish():
    """
    Formularz do wprowadzania treści posta i wgrywania pliku,
    a następnie wywołanie automatyzacji publikacji (Selenium).
    """
    form_html = '''
    <!DOCTYPE html>
    <html lang="pl">
    <head>
      <meta charset="UTF-8">
      <title>Publikacja na Facebook</title>
      <style>
        body { font-family: Arial, sans-serif; background-color: #f2f2f2; }
        .container {
          max-width: 600px; margin: 30px auto; background: #fff; padding: 20px; 
          border-radius: 8px; box-shadow: 0 2px 5px rgba(0,0,0,0.2);
        }
        h1 { margin-bottom: 20px; }
        label { display: block; margin: 10px 0 5px; }
        input[type="file"], textarea, input[type="text"] {
          width: 100%; padding: 8px; border: 1px solid #ccc; border-radius: 4px;
        }
        button { margin-top: 15px; padding: 10px 20px; background: #1f8ef1; color: #fff; border: none; border-radius: 4px; cursor: pointer; }
        button:hover { background: #0a6db9; }
        .back-link { display: inline-block; margin-top: 20px; }
      </style>
    </head>
    <body>
      <div class="container">
        <h1>Publikacja na Facebook</h1>
        <form method="POST" enctype="multipart/form-data">
          <label for="post_text">Treść posta:</label>
          <textarea id="post_text" name="post_text" rows="4" required></textarea>
          
          <label for="media_file">Załącz plik (obrazek lub wideo MP4, opcjonalnie):</label>
          <input type="file" id="media_file" name="media_file" accept="image/*,video/mp4">
          
          <button type="submit">Publikuj</button>
        </form>
        <p class="back-link"><a href="{{ url_for('automation.automation_facebook') }}">Powrót</a></p>
      </div>
    </body>
    </html>
    '''

    if request.method == 'GET':
        return render_template_string(form_html)

    # POST:
    post_text = request.form.get('post_text', '').strip()
    media_file = request.files.get('media_file')

    # Walidacja minimalna
    if not post_text:
        flash("Treść posta jest wymagana.", "error")
        return render_template_string(form_html)

    # Jeśli wybrano plik, zapisz go lokalnie w folderze "uploads"
    file_path = None
    if media_file and media_file.filename:
        uploads_dir = os.path.join(os.getcwd(), 'uploads')
        os.makedirs(uploads_dir, exist_ok=True)
        
        safe_filename = media_file.filename  # w praktyce sanitacja
        file_path = os.path.join(uploads_dir, safe_filename)
        media_file.save(file_path)

    # Wywołanie Selenium
    try:
        report = publish_post_to_facebook(post_text=post_text, file_path=file_path)
        flash("Post został opublikowany. Sprawdź konsolę lub raport e-mail.", "success")
    except Exception as e:
        flash(f"Wystąpił błąd: {str(e)}", "error")

    return redirect(url_for('automation.automation_facebook_publish'))

