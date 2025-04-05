from flask import Blueprint, render_template_string, url_for

automation_bp = Blueprint('automation', __name__, url_prefix='/automation')

@automation_bp.route('/')
def automation_home():
    automation_home_template = '''
    <!DOCTYPE html>
    <html lang="pl">
    <head>
        <meta charset="UTF-8">
        <title>Automation - Główna</title>
        <style>
            body { font-family: Arial, sans-serif; background-color: #f2f2f2; }
            .container {
                max-width: 600px;
                margin: 50px auto;
                background: #fff;
                padding: 20px;
                border-radius: 8px;
                box-shadow: 0 2px 5px rgba(0,0,0,0.2);
            }
            h1 { margin-bottom: 20px; }
            a {
                display: block;
                padding: 10px;
                margin: 5px 0;
                background-color: #1f8ef1;
                color: #fff;
                text-decoration: none;
                border-radius: 5px;
                text-align: center;
            }
            a:hover { background-color: #0a6db9; }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>Panel Automatyzacji</h1>
            <p>Wybierz platformę, którą chcesz konfigurować lub automatyzować:</p>
            <a href="{{ url_for('automation.automation_tiktok') }}">TikTok</a>
            <a href="{{ url_for('automation.automation_facebook') }}">Facebook</a>
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

@automation_bp.route('/tiktok/plan')
def automation_tiktok_plan():
    plan_template = '''
    <!DOCTYPE html>
    <html lang="pl">
    <head><title>Plan Treści (TikTok)</title></head>
    <body>
        <h1>Plan Treści dla TikToka</h1>
        <p>Tu opisujesz organizację i plan treści.</p>
        <p><a href="{{ url_for('automation.automation_tiktok') }}">Powrót do sekcji TikTok</a></p>
    </body>
    </html>
    '''
    return render_template_string(plan_template)

@automation_bp.route('/tiktok/rodzaje')
def automation_tiktok_rodzaje():
    rodzaje_template = '''
    <!DOCTYPE html>
    <html lang="pl">
    <head><title>Rodzaje wideo (TikTok)</title></head>
    <body>
        <h1>Rodzaje wideo na TikToku</h1>
        <p>Krótki opis: poradniki, Q&A, kulisy pracy itp.</p>
        <p><a href="{{ url_for('automation.automation_tiktok') }}">Powrót do sekcji TikTok</a></p>
    </body>
    </html>
    '''
    return render_template_string(rodzaje_template)

@automation_bp.route('/tiktok/scenariusze')
def automation_tiktok_scenariusze():
    scenariusze_template = '''
    <!DOCTYPE html>
    <html lang="pl">
    <head><title>Scenariusze Postów (TikTok)</title></head>
    <body>
        <h1>Scenariusze Postów i Wytyczne</h1>
        <p>Tu możesz umieścić schematy i przykłady konkretnych postów.</p>
        <p><a href="{{ url_for('automation.automation_tiktok') }}">Powrót do sekcji TikTok</a></p>
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
