from flask import Blueprint, render_template_string, url_for

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
            body {
                font-family: Arial, sans-serif;
                background-color: #f2f2f2;
                margin: 0;
                padding: 0;
            }
            .container {
                max-width: 800px;
                margin: 40px auto;
                background-color: #fff;
                padding: 40px;
                box-shadow: 0 4px 8px rgba(0,0,0,0.1);
                position: relative;
                min-height: 100vh;
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
                margin-bottom: 20px;
            }
            p {
                text-align: left;
                margin-bottom: 20px;
            }
            .platform-list a {
                display: block;
                margin: 10px 0;
                padding: 10px;
                background-color: #1f8ef1;
                color: #fff;
                text-decoration: none;
                border-radius: 4px;
                text-align: left;
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

@automation_bp.route('/tiktok/plan')
def automation_tiktok_plan():
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
             margin: 0 auto;
             background-color: #fff;
             padding: 40px;
             position: relative;
             box-shadow: 0 4px 8px rgba(0,0,0,0.1);
             min-height: 100vh;
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
         <h1>Plan Treści dla TikToka</h1>
         <p>Tu opisujesz organizację i plan treści dla TikToka.</p>
      </div>
    </body>
    </html>
    '''
    return render_template_string(plan_template)


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
             position: relative;
             box-shadow: 0 4px 8px rgba(0,0,0,0.1);
             min-height: 100vh;
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
             position: relative;
             box-shadow: 0 4px 8px rgba(0,0,0,0.1);
             min-height: 100vh;
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
