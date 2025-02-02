import os
import threading
import logging
from dotenv import load_dotenv
import sys
from flask import Flask, render_template_string, request, redirect, url_for, flash, session, send_from_directory, jsonify
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication
import smtplib
import base64
import json
from google.oauth2 import service_account
from googleapiclient.discovery import build
from flask_sqlalchemy import SQLAlchemy
from werkzeug.utils import secure_filename
from flask_migrate import Migrate
from google.cloud import storage  # <-- GCS import
import uuid
from datetime import datetime, timedelta, timezone
from werkzeug.security import generate_password_hash, check_password_hash
import re
from random import randint
# from flask_mail import Mail, Message
from models import db, User, LicenseKey, Note, VerificationCode
from cryptography.fernet import Fernet
from werkzeug.exceptions import RequestEntityTooLarge
import magic  # Upewnij się, że ta biblioteka jest zainstalowana
import bleach
from flask import jsonify
from email.message import EmailMessage
import mimetypes
import ssl

# ------------------------------
# *** KONFIGURACJA CELERY W TYM SAMYM PLIKU ***
# ------------------------------
from celery import Celery

# Wczytanie zmiennych środowiskowych (lokalnie z .env, na Heroku z Config Vars)
load_dotenv()

# REDIS_URL może być np. "redis://:p4ss@host:6379" albo "rediss://:p4ss@host:6379?ssl_cert_reqs=none"
redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")

celery_app = Celery(
    "app",
    broker=redis_url,
    backend=redis_url
)

# Jeżeli rediss:// jest używane i chcesz ominąć certyfikaty (np. "?ssl_cert_reqs=none"), to:
if redis_url.startswith("rediss://"):
    celery_app.conf.update(
        broker_transport_options={
            'visibility_timeout': 3600,  # 1 godz. rezerwacji zadań w kolejce
            'ssl_cert_reqs': 'CERT_NONE'
        },
        result_backend_transport_options={
            'ssl_cert_reqs': 'CERT_NONE'
        }
    )

# Dodaj bieżący katalog do ścieżki Pythona
sys.path.append(os.path.abspath(os.getcwd()))

# Inicjalizacja aplikacji Flask
app = Flask(__name__)
basedir = os.path.abspath(os.path.dirname(__file__))

# Konfiguracja bazy danych (Heroku/Postgres lub SQLite)
database_url = os.getenv("DATABASE_URL")
if database_url:
    if database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql://", 1)
    print(f"Używana baza danych: {database_url}")
else:
    # Jeśli lokalnie brak DATABASE_URL => SQLite
    database_url = 'sqlite:///' + os.path.join(basedir, 'users.db')
    print(f"Używana baza danych (lokalny SQLite): {database_url}")

app.config['SQLALCHEMY_DATABASE_URI'] = database_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Podstawowa konfiguracja
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'default_secret_key')
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16 MB

# Bezpieczne ustawienia ciasteczek sesji
app.config['SESSION_COOKIE_SECURE'] = False  # Ustaw True w produkcji (HTTPS)
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'

# Inicjalizacja szyfrowania (Fernet)
ENCRYPTION_KEY = os.getenv('ENCRYPTION_KEY')
if not ENCRYPTION_KEY:
    raise ValueError("Brak zmiennej ENCRYPTION_KEY w środowisku!")
fernet = Fernet(ENCRYPTION_KEY.encode())

# Konfiguracja Flask-Mail (tylko serwer + port + TLS; bez hasła globalnego!)
app.config['MAIL_SERVER'] = 'smtp.office365.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True

# UWAGA: Usuwamy/zakomentowujemy globalne MAIL_USERNAME / MAIL_PASSWORD z .env
# (Niepotrzebne, bo korzystamy z hasła usera z bazy!)
# MAIL_USERNAME = os.getenv('MAIL_USERNAME')
# MAIL_PASSWORD_ENCRYPTED = os.getenv('MAIL_PASSWORD')
# try:
#     MAIL_PASSWORD = fernet.decrypt(MAIL_PASSWORD_ENCRYPTED.encode()).decode()
# except:
#     MAIL_PASSWORD = MAIL_PASSWORD_ENCRYPTED
# app.config['MAIL_USERNAME'] = MAIL_USERNAME
# app.config['MAIL_PASSWORD'] = MAIL_PASSWORD

db.init_app(app)
migrate = Migrate(app, db)
# mail = Mail(app)

# Globalne słowniki do śledzenia postępu i zatrzymywania wysyłki e-maili (opcjonalnie)
email_sending_progress = {}
email_sending_stop_events = {}

# Katalog do przechowywania załączników
UPLOAD_FOLDER = os.path.join(app.root_path, 'uploads')
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# ----------------------------------------
# KONFIGURACJA GOOGLE CLOUD STORAGE
# ----------------------------------------
creds_b64 = os.getenv("GOOGLE_CREDENTIALS_BASE64")
if not creds_b64:
    raise ValueError("Brak zmiennej GOOGLE_CREDENTIALS_BASE64 – nie można zainicjalizować GCS.")

try:
    creds_json = base64.b64decode(creds_b64).decode("utf-8")
    creds_info = json.loads(creds_json)
    credentials = service_account.Credentials.from_service_account_info(creds_info)
except Exception as e:
    raise ValueError(f"Nie udało się zdekodować klucza GCP: {e}")

storage_client = storage.Client(credentials=credentials)
GCS_BUCKET = os.getenv('GCS_BUCKET_NAME')
if not GCS_BUCKET:
    raise ValueError("Brak zmiennej środowiskowej GCS_BUCKET_NAME!")
bucket = storage_client.bucket(GCS_BUCKET)

# Dozwolone typy plików
ALLOWED_EXTENSIONS = {
    'png', 'jpg', 'jpeg', 'gif', 'pdf', 'doc', 'docx', 'xls', 'xlsx', 'txt', 'zip'
}
app.config['MAX_ATTACHMENTS'] = 5

# Konfiguracja Google Sheets API (o ile potrzebne)
SCOPES = ['https://www.googleapis.com/auth/spreadsheets.readonly']
SPREADSHEET_ID = os.getenv('SPREADSHEET_ID', '')


def is_allowed_file(file):
    """
    Sprawdza, czy plik ma dozwolone rozszerzenie i prawidłowy typ MIME.
    """
    if '.' not in file.filename or file.filename.rsplit('.', 1)[1].lower() not in ALLOWED_EXTENSIONS:
        return False

    file.seek(0)
    mime_type = magic.from_buffer(file.read(1024), mime=True)
    file.seek(0)

    allowed_mime_types = [
        'application/pdf',
        'image/jpeg',
        'image/png',
        'image/gif',
        'application/msword',
        'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        'application/vnd.ms-excel',
        'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        'text/plain',
        'application/zip'
    ]
    return mime_type in allowed_mime_types


def upload_file_to_gcs(file, expiration=3600):
    """
    Przesyła plik do GCS i zwraca signed URL.
    """
    try:
        filename = secure_filename(file.filename)
        blob = bucket.blob(filename)

        # Ustalenie MIME
        sample = file.read(1024)
        mime_type = magic.from_buffer(sample, mime=True)
        file.seek(0)

        blob.upload_from_file(file, content_type=mime_type)
        signed_url = blob.generate_signed_url(expiration=timedelta(seconds=expiration))
        return signed_url
    except Exception as e:
        app.logger.error(f"Nie udało się przesłać pliku {file.filename} do GCS: {e}")
        return False


@app.errorhandler(RequestEntityTooLarge)
def handle_file_too_large(e):
    flash('Przesłany plik jest za duży. Maksymalny rozmiar to 16 MB.', 'error')
    return redirect(url_for('index'))


# Szablon podpisu do e-maila
EMAIL_SIGNATURE_TEMPLATE = """
<br><br>
<table cellpadding="0" cellspacing="0" border="0" style="font-family: Calibri, sans-serif; font-size: 16px;">
    <tr>
        <td>
            <!-- Powitanie -->
            <p style="margin: 0 0 10px 0; color: #000000;">Best regards, Mit freundlichen Grüßen, 谨致问候</p>
            
            <!-- Imię, Nazwisko i Stanowisko -->
            <p style="margin: 0 0 5px 0; font-weight: bold; color: #003366;">{first_name} {last_name}<br>{position}</p>
            
            <!-- Informacje o firmie -->
            <p style="margin: 0 0 10px 0; color: #3399FF;">DLG Logistics Poland sp. z o.o.<br>Wioślarska 8, 00-411 Warszawa</p>
            
            <!-- Dane kontaktowe -->
            <p style="margin: 0 0 10px 0; color: #3399FF;">
                {phone_number}<br>
                <a href="mailto:{email_address}" style="color: #3399FF; text-decoration: underline;">{email_address}</a><br>
                <a href="http://www.dlglogistics.pl" style="color: #3399FF; text-decoration: underline;">www.dlglogistics.pl</a>
            </p>
            
            <!-- Logo DLG i LOGISTICS GROUP -->
            <table cellpadding="0" cellspacing="0" border="0" style="margin: 0; line-height: 1; font-family: Arial, sans-serif;">
                <tr>
                    <td style="font-size: 48px; font-weight: bold; color: #003366; padding: 0; text-align: left;">
                        <a href="http://www.dlglogistics.pl" style="text-decoration: none; color: #003366;">DLG</a>
                    </td>
                </tr>
                <tr>
                    <td style="font-size: 12px; color: #003366; padding: 0; text-align: left;">
                        <a href="http://www.dlglogistics.pl" style="text-decoration: none; color: #003366;">LOGISTICS GROUP</a>
                    </td>
                </tr>
            </table>
            
            <!-- Tekst prawny -->
            <p style="margin: 20px 0 0 0; font-size: 9.5px; color: #888888;">
                This e-mail is intended solely for the person to whom it is addressed. ...
            </p>
        </td>
    </tr>
</table>
"""


# Przykładowa funkcja pobierająca dane z Google Sheet (jeśli potrzebne)
def get_data_from_sheet():
    credentials_b64 = os.getenv('GOOGLE_CREDENTIALS_BASE64')
    if credentials_b64:
        credentials_json = base64.b64decode(credentials_b64).decode('utf-8')
        credentials_info = json.loads(credentials_json)
        credentials = service_account.Credentials.from_service_account_info(credentials_info, scopes=SCOPES)
    else:
        raise ValueError("GOOGLE_CREDENTIALS_BASE64 not set in environment variables.")
    
    service = build('sheets', 'v4', credentials=credentials)
    sheet = service.spreadsheets()
    RANGE_NAME = 'A1:AX'  # 50 kolumn
    
    result = sheet.values().get(spreadsheetId=SPREADSHEET_ID, range=RANGE_NAME).execute()
    data = result.get('values', [])
    
    # Uzupełnianie brakujących kolumn do 50
    for i, row in enumerate(data):
        if len(row) < 50:
            row.extend([''] * (50 - len(row)))
        print(f"Wiersz {i+1} ma {len(row)} kolumn")
    
    return data

# Funkcja zwracająca listę segmentów
def get_segments():
    """
    Zwraca listę segmentów w ustalonej kolejności.
    """
    return [
        "TSL World", "TSL EU", "TSL - World; West / East without BY&RU; EU",
        "TSL West / East without BY&RU", "OTKPMM FCL / combi FTL",
        "OTKPLSH FCL / combi FTL", "OTKPS", "OTKPT", "OTKPB",
        "OKW", "OKW 20'", "Containers PL / non-normative",
        "WT Premium", "WT Premium / Sea", "WT Premium / Rail", "Foreign EU / FCL, LCL",
        "Foreign EU / LCL / FCL / REF",
        "FCL / West / South", "FCL / LCL / FTL / LTL / BALKANS / South", "OTKPMM FCL heavy",
        "Foreign EU / FTL, LTL, FCL, LCL",
        "Foreign EU / FTL, LTL, FCL, LCL no UA,BY,RU",
        "Foreign EU / FTL, LTL, FCL, LCL from/to UA",
        "Foreign EU / FTL, LTL, FCL, LCL, ADR no UA,BY,RU",
        "Foreign EU / FTL, LTL, FCL, LCL no FR",
        "Foreign EU / FTL, LTL, FCL, LCL + REF",
        "Foreign EU + Scandinavie / FTL, LTL, FCL, LCL", "Ukraine - Europe - Ukraine",
        "Foreign EU / FTL, LTL", "Foreign EU / FTL, LTL, REF",
        "Foreign EU / FTL +REF +ADR",
        "Foreign EU / FTL, LTL from PL to CZ & EE",
        "FTL / LTL + ADR Poland & Switzerland", "FLT / LTL with lift",
        "FTL K", "Only REF", "LTL", "FTL / LTL K", "LTL K",
        "LTL East Europe", "KOPER", "Only start from Koper",
        "Turkey carriers TIMOKOM", "double-deck car carrier",
        "CARGO Europe / Russia, Turkey, Asia",
        "Foreign EU / only open trailers", "Central Europe",
        "PL REF", "Central Europe only FTL", "Agency", "Rail Global", "DLG", "NON", "NEW1", 
        "NEW2","NEW3","NEW2025_1", "NEW2025_2", "NEW2025_3", "NEW2025_4", "NEW2025_5"
    ]

# Funkcja licząca unikalne segmenty
def get_unique_segments_with_counts(data):
    """
    Pobiera unikalne segmenty i liczy wystąpienia dla 'Polski' i 'Zagraniczny'.
    """
    ordered_segments = get_segments()
    segments = {segment: {"Polski": 0, "Zagraniczny": 0} for segment in ordered_segments}

    for row in data:
        if len(row) > 16 and row[16]:
            segment = row[16]
            subsegment = row[23] if len(row) > 23 else ""
            if segment in segments:
                if subsegment == "Polski":
                    segments[segment]["Polski"] += 1
                elif subsegment == "Zagraniczny":
                    segments[segment]["Zagraniczny"] += 1
    return segments

# Funkcja pobierająca e-maile dla segmentu
def get_emails_for_segment(data, segment, subsegment):
    """
    Pobiera adresy e-mail dla danego segmentu i podsegmentu.
    """
    emails = []
    for row in data:
        if len(row) > 23 and row[16] == segment and row[23] == subsegment:
            email = row[17].strip() if len(row) > 17 else ""
            if email:
                emails.append(email)
    return emails

def get_email_company_pairs_for_segment(data, segment, subsegment):
    """
    Pobiera pary adres e-mail i nazwa firmy dla danego segmentu i podsegmentu.
    """
    pairs = []
    for row in data:
        if len(row) > 23 and row[16] == segment and row[23] == subsegment:
            email = row[17].strip() if len(row) > 17 else ""
            company = row[20].strip() if len(row) > 20 else ""
            if email and company:
                pairs.append({'email': email, 'company': company})
    return pairs

# Funkcja do uzyskania unikalnych możliwości z firmami
def get_unique_possibilities_with_companies(data):
    possibilities = {}
    for row_index, row in enumerate(data):
        company = row[20].strip() if len(row) > 20 and row[20] else "Nieznana Firma"
        email = row[17].strip() if len(row) > 17 and row[17] else ""

        if len(row) != 50:
            print(f"Wiersz {row_index+1} ma niepoprawną liczbę kolumn: {len(row)}")
            continue

        # Iteracja przez kolumny Z do AH (indeksy 25 do 33)
        for i in range(25, 34):
            possibility = row[i].strip() if row[i] else ''
            if possibility:
                if possibility not in possibilities:
                    possibilities[possibility] = []
                possibilities[possibility].append({'email': email, 'company': company})
                print(f"Znaleziona możliwość '{possibility}' w wierszu {row_index+1} dla firmy '{company}'")
    return possibilities

def get_potential_clients(data):
    """
    Pobiera potencjalnych klientów z danych arkusza.

    Kolumny:
        - AT: Nazwa firmy (45)
        - AU: Adres email (46)
        - AV: Grupa (47)
        - AX: Język (49)

    Zwraca:
        Słownik z grupami jako kluczami, a listami klientów jako wartościami.
    """
    potential_clients = {}
    for idx, row in enumerate(data):
        print(f"Wiersz {idx} ma długość {len(row)}")
        if len(row) > 49:
            group = row[47]  # AV
            email = row[46]  # AU
            company = row[45]  # AT
            language = row[49]  # AX
            print(f"Wiersz {idx}: group='{group}', email='{email}', company='{company}', language='{language}'")
            if group and email and company and language:
                group = group.strip()
                email = email.strip()
                company = company.strip()
                language = language.strip()
                if group not in potential_clients:
                    potential_clients[group] = []
                potential_clients[group].append({
                    'email': email,
                    'company': company,
                    'language': language
                })
            else:
                print(f"Wiersz {idx} pominięty z powodu brakujących danych.")
        else:
            print(f"Wiersz {idx} pominięty z powodu niewystarczającej długości.")
    # Logowanie liczby grup i klientów
    print(f"Pobrano {len(potential_clients)} grup potencjalnych klientów.")
    total_clients = sum(len(clients) for clients in potential_clients.values())
    print(f"Pobrano {total_clients} potencjalnych klientów.")
    return potential_clients


# Funkcja: Wysyłanie pojedynczego e-maila
def send_email(to_email, subject, body, user, attachments=None):
    """
    Wysyła e-mail za pomocą indywidualnego hasła usera (odszyfrowanego).
    """
    try:
        # Odszyfruj hasło z bazy (kolumna user.email_password)
        email_password_encrypted = user.email_password
        email_password = fernet.decrypt(email_password_encrypted.encode()).decode()

        # Formatowanie nr telefonu
        formatted_phone_number = format_phone_number(user.phone_number)

        # Podpis (signature)
        signature = EMAIL_SIGNATURE_TEMPLATE.format(
            first_name=user.first_name,
            last_name=user.last_name,
            position=user.position,
            phone_number=formatted_phone_number,
            email_address=user.email_address
        )

        # Treść wiadomości (HTML + styl akapitów)
        message_body = f'''
        <div style="font-family: Calibri, sans-serif; font-size: 11pt;">
            <style>
                p {{
                    margin: 0;
                    line-height: 1.2;
                }}
                p + p {{
                    margin-top: 10px;
                }}
            </style>
            {body}
        </div>
        '''

        # Połączenie treści z podpisem
        body_with_signature = f'''
        {message_body}
        {signature}
        '''

        # Tworzenie wiadomości MIME
        msg = MIMEMultipart()
        msg['Subject'] = subject
        msg['From'] = user.email_address
        msg['To'] = to_email
        msg['Reply-To'] = user.email_address
        msg.attach(MIMEText(body_with_signature, 'html'))

        # Dodawanie załączników
        if attachments:
            for file_path in attachments:
                if not os.path.exists(file_path):
                    app.logger.error(f"Załącznik nie istnieje: {file_path}")
                    continue
                try:
                    with open(file_path, 'rb') as f:
                        part = MIMEApplication(f.read(), Name=os.path.basename(file_path))
                        part['Content-Disposition'] = f'attachment; filename="{os.path.basename(file_path)}"'
                        msg.attach(part)
                except Exception as e:
                    app.logger.error(f"Nie udało się dołączyć załącznika {file_path}: {e}")

        # Wysłanie maila
        smtp_server = app.config['MAIL_SERVER']
        smtp_port = app.config['MAIL_PORT']
        smtp_use_tls = app.config['MAIL_USE_TLS']

        with smtplib.SMTP(smtp_server, smtp_port) as server:
            if smtp_use_tls:
                server.starttls()
            server.login(user.email_address, email_password)
            server.send_message(msg)
            app.logger.info(f"E-mail wysłany do: {to_email}")

    except Exception as e:
        app.logger.error(f"Błąd wysyłania e-maila do {to_email}: {str(e)}")
        raise e


def format_phone_number(phone_number):
    """
    Przykładowe formatowanie +48 xxxxxx
    """
    if phone_number.startswith('+48') and len(phone_number) == 12 and phone_number[3:].isdigit():
        return f"{phone_number[:3]} {phone_number[3:6]} {phone_number[6:9]} {phone_number[9:]}"
    else:
        return phone_number


# -------------
# CELERY TASK
# -------------
@celery_app.task(bind=True)
def send_bulk_emails(self, emails, subject, body, user_id, attachment_paths=None):
    """
    Zadanie Celery do masowej wysyłki. Wysyła e-maile do listy 'emails' w jednym podejściu.
    """
    with app.app_context():
        user = db.session.get(User, user_id)
        if not user:
            raise ValueError(f"Brak użytkownika o ID: {user_id}")

        sent_count = 0
        total = len(emails)

        for email in emails:
            try:
                send_email(
                    to_email=email,
                    subject=subject,
                    body=body,
                    user=user,
                    attachments=attachment_paths
                )
                sent_count += 1

                # Opcjonalne raportowanie postępu
                self.update_state(
                    state='PROGRESS',
                    meta={'current': sent_count, 'total': total}
                )

            except Exception as e:
                app.logger.error(f"Błąd wysyłania do {email}: {e}")
                # Nie przerywaj pętli, ewentualnie loguj błędy

        return {
            'state': 'SUCCESS',
            'current': total,
            'total': total,
            'status': f'Wysłano {sent_count} / {total} e-maili'
        }


# -------------
# TRASY
# -------------

@app.route('/test_email')
def test_email():
    """
    Prosty test wysyłki do pierwszego usera w bazie.
    """
    user = User.query.first()
    if not user:
        flash('Brak użytkownika w bazie do wysłania testu.', 'error')
        return redirect(url_for('index'))

    subject = "Testowy E-mail z Załącznikiem"
    body = "To jest testowy e-mail z załącznikiem."
    test_attachment = os.path.join(app.config['UPLOAD_FOLDER'], 'test_attachment.pdf')

    if not os.path.exists(test_attachment):
        try:
            with open(test_attachment, 'wb') as f:
                f.write('To jest testowy załącznik.'.encode('utf-8'))
        except Exception as e:
            app.logger.error(f"Nie udało się utworzyć testowego załącznika: {e}")
            flash('Błąd podczas tworzenia testowego załącznika.', 'error')
            return redirect(url_for('index'))

    try:
        send_email(user.email_address, subject, body, user, attachments=[test_attachment])
        flash('Testowy e-mail został wysłany.', 'success')
    except Exception as e:
        flash(f'Błąd wysyłania testowego e-maila: {e}', 'error')

    return redirect(url_for('index'))


def get_email_subsegment_mapping(data):
    """
    Zwraca słownik mapujący adresy e-mail do podsegmentów ('Polski' lub 'Zagraniczny').
    """
    email_subsegment = {}
    for row in data:
        if len(row) > 23:
            email = row[17].strip() if len(row) > 17 else ""
            subsegment = row[23] if len(row) > 23 else ""
            if email and subsegment:
                email_subsegment[email] = subsegment
    return email_subsegment


@app.route('/send_message', methods=['POST'])
def send_message():
    """
    Trasa do wysyłki e-maili w jednym podejściu do wielu odbiorców
    (z wykorzystaniem Celery).
    """
    if 'user_id' not in session:
        flash('Nie jesteś zalogowany.', 'error')
        return redirect(url_for('login'))

    user_id = session['user_id']
    user = db.session.get(User, user_id)
    if not user:
        flash('Użytkownik nie istnieje.', 'error')
        return redirect(url_for('login'))

    subject = request.form.get('subject')
    message = request.form.get('message')
    include_emails = request.form.getlist('include_emails')
    attachments = request.files.getlist('attachments')

    if not subject or not message:
        flash('Uzupełnij temat i treść wiadomości.', 'error')
        return redirect(url_for('index'))

    if not include_emails:
        flash('Wybierz co najmniej jeden adres e-mail.', 'error')
        return redirect(url_for('index'))

    # Obsługa załączników
    attachment_filenames = []
    for file in attachments:
        if file and is_allowed_file(file):
            filename = secure_filename(file.filename)
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(filepath)
            attachment_filenames.append(filepath)
        elif file.filename != '':
            flash(f'Nieprawidłowy typ pliku: {file.filename}', 'error')
            return redirect(url_for('index'))

    try:
        # Wywołanie asynchronicznego zadania Celery
        task = send_bulk_emails.delay(
            include_emails,
            subject,
            message,
            user_id,
            attachment_filenames
        )
        flash('Rozpoczęto asynchroniczną wysyłkę e-maili.', 'success')
        return redirect(url_for('index'))
    except Exception as e:
        app.logger.error(f'Błąd podczas inicjowania zadania Celery: {e}')
        flash('Wystąpił błąd podczas wysyłania wiadomości.', 'error')
        return redirect(url_for('index'))


@app.errorhandler(RequestEntityTooLarge)
def handle_request_entity_too_large(e):
    flash('Przesłany plik jest za duży. Maksymalny rozmiar to 16 MB.', 'error')
    return redirect(url_for('index'))


# Asynchroniczne API do wysyłania e-maili (przykład)
@app.route('/send_message_ajax', methods=['POST'])
def send_message_ajax():
    """
    Wersja z dodatkowym print (app.logger.info) w budowaniu słownika
    email->język, żebyśmy mogli prześledzić w logach, co się faktycznie
    odczytuje z arkusza Google.
    """
    # 1. Sprawdzenie, czy użytkownik jest zalogowany.
    if 'user_id' not in session:
        return jsonify({'success': False, 'message': 'Nie jesteś zalogowany.'}), 401

    user_id = session['user_id']
    user = db.session.get(User, user_id)
    if not user:
        return jsonify({'success': False, 'message': 'Użytkownik nie istnieje.'}), 404

    # 2. Pobranie danych z formularza
    subject = request.form.get('subject')
    message = request.form.get('message')
    recipients = request.form.get('recipients', '')
    attachments = request.files.getlist('attachments')
    language = request.form.get('language', '').strip()

    # Walidacja
    if not subject or not message:
        return jsonify({'success': False, 'message': 'Wypełnij wszystkie wymagane pola (temat i treść).'}), 400
    if not language:
        return jsonify({'success': False, 'message': 'Nie wybrano języka (Polski / Zagraniczny).'}), 400

    # 3. Rozbicie recipients na listę e-maili
    valid_emails = []
    raw_recipients = recipients.replace(';', ',')
    for email in raw_recipients.split(','):
        clean = email.strip()
        if clean:
            valid_emails.append(clean)

    if not valid_emails:
        return jsonify({'success': False, 'message': 'Proszę wybrać przynajmniej jeden adres e-mail.'}), 400

    # 4. Obsługa załączników
    attachment_filenames = []
    for file in attachments:
        if file and is_allowed_file(file.filename):
            filename = secure_filename(file.filename)
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(filepath)
            attachment_filenames.append(filepath)
        elif file.filename != '':
            return jsonify({'success': False, 'message': f'Nieprawidłowy typ pliku: {file.filename}'}), 400

    # 5. Pobranie danych z Google Sheet + zbudowanie słownika email->język
    data = get_data_from_sheet()
    email_language_map = {}

    for row_index, row in enumerate(data):
        # Segmenty / możliwości: row[17] = e-mail, row[23] = subsegment
        if len(row) > 23 and row[17] and row[23]:
            em = row[17].strip()
            subseg = row[23].strip()
            # *** PRINT / LOG: pokażemy co się dzieje
            app.logger.info(f"[DEBUG] SEG row {row_index}: email={em}, subseg='{subseg}'")
            email_language_map[em] = subseg

        # Potencjalni klienci: row[46] = e-mail, row[49] = język
        if len(row) > 49 and row[46] and row[49]:
            em = row[46].strip()
            lng = row[49].strip()
            # *** PRINT / LOG: 
            app.logger.info(f"[DEBUG] POTC row {row_index}: email={em}, lang='{lng}'")
            email_language_map[em] = lng

    # 6. Filtr: zostaw tylko e-maile, które mają w tym słowniku
    # identyczny język jak user wybrał w formularzu
    filtered_emails = []
    for e in valid_emails:
        mail_lang = email_language_map.get(e, "")
        app.logger.info(f"[DEBUG] Checking email={e}, mail_lang='{mail_lang}', user_chosen='{language}'")
        if mail_lang == language:
            filtered_emails.append(e)

    if not filtered_emails:
        return jsonify({
            'success': False,
            'message': f'Żaden z zaznaczonych adresów nie pasuje do języka: {language}.'
        }), 400

    # 7. Wysyłanie przez Celery (asynchroniczne)
    try:
        import uuid
        task_id = str(uuid.uuid4())
        stop_event = threading.Event()
        email_sending_stop_events[task_id] = stop_event

        task = send_bulk_emails.delay(
            filtered_emails,
            subject,
            message,
            user_id,
            attachment_filenames
        )

        return jsonify({
            'success': True,
            'message': f'Rozpoczęto wysyłanie wiadomości (język: {language}).',
            'task_id': task.id
        }), 200

    except Exception as e:
        app.logger.error(f'Błąd: {e}')
        return jsonify({'success': False, 'message': 'Błąd podczas wysyłania.'}), 500



# Funkcja zatrzymująca proces wysyłania (opcjonalna)
@app.route('/stop_sending/<task_id>', methods=['POST'])
def stop_sending(task_id):
    stop_event = email_sending_stop_events.get(task_id)
    if stop_event:
        stop_event.set()
        return jsonify({'success': True, 'message': 'Proces wysyłania zatrzymany.'}), 200
    else:
        return jsonify({'success': False, 'message': 'Nie znaleziono zadania.'}), 404


@app.route('/email_progress/<task_id>')
def email_progress(task_id):
    """
    Zwraca aktualny postęp wysyłania e-maili w %.
    """
    # Wersja Celery:
    # Odczyt stanu zadania
    res = send_bulk_emails.AsyncResult(task_id)
    if res.state == 'PROGRESS':
        current = res.info.get('current', 0)
        total = res.info.get('total', 1)
        percentage = (current / total) * 100
        return jsonify({'percentage': percentage, 'state': res.state})
    elif res.state in ('SUCCESS', 'FAILURE'):
        return jsonify({'percentage': 100, 'state': res.state})
    else:
        return jsonify({'percentage': 0, 'state': res.state})


# Przykład wysyłania kodu weryfikacyjnego (opcjonalnie)
def send_verification_email(user, code):
    subject = "Kod weryfikacyjny..."
    body = f"..."
    try:
        send_email(
            to_email=user.email_address,
            subject=subject,
            body=body,
            user=user  # i ewentualnie attachments, jeśli chcesz
        )
        app.logger.info(f"E-mail weryfikacyjny wysłany do {user.email_address}.")
        return True
    except Exception as e:
        app.logger.error(f"Błąd wysyłania e-maila do {user.email_address}: {e}")
        return False


@app.route('/add_note_ajax', methods=['POST'])
def add_note_ajax():
    if 'user_id' not in session:
        return jsonify({'success': False, 'message': 'Nie jesteś zalogowany.'}), 401

    data = request.get_json()
    note_content = data.get('note') if data else None
    user_id = session['user_id']

    if note_content and note_content.strip():
        new_note = Note(content=note_content.strip(), user_id=user_id)
        db.session.add(new_note)
        try:
            db.session.commit()
            notes = Note.query.filter_by(user_id=user_id).all()
            notes_data = [
                {
                    'id': note.id,
                    'content': note.content,
                    'user': {
                        'first_name': note.user.first_name,
                        'last_name': note.user.last_name,
                        'color': note.user.color,
                        'email': note.user.email_address
                    }
                } for note in notes
            ]
            return jsonify({'success': True, 'message': 'Notatka została dodana.', 'notes': notes_data}), 200
        except Exception as e:
            db.session.rollback()
            app.logger.error(f"Błąd: {e}")
            return jsonify({'success': False, 'message': f'Błąd przy dodawaniu notatki: {e}'}), 500
    else:
        return jsonify({'success': False, 'message': 'Nie można dodać pustej notatki.'}), 400


@app.route('/edit_note_ajax', methods=['POST'])
def edit_note_ajax():
    if 'user_id' not in session:
        return jsonify({'success': False, 'message': 'Nie jesteś zalogowany.'}), 401

    user_id = session['user_id']
    user = db.session.get(User, user_id)
    if not user:
        return jsonify({'success': False, 'message': 'Użytkownik nie istnieje.'}), 404

    data = request.get_json()
    note_id = data.get('note_id')
    new_content = data.get('new_content')

    if not note_id or not new_content:
        return jsonify({'success': False, 'message': 'Brakuje ID notatki lub nowej treści.'}), 400

    note = Note.query.get(note_id)
    if not note or note.user_id != user_id:
        return jsonify({'success': False, 'message': 'Notatka nie istnieje lub brak dostępu.'}), 404

    try:
        note.content = new_content.strip()
        db.session.commit()
        return jsonify({'success': True, 'message': 'Notatka zaktualizowana.', 'note': {'id': note.id, 'content': note.content}})
    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Błąd: {e}")
        return jsonify({'success': False, 'message': 'Błąd podczas aktualizacji notatki.'}), 500


@app.route('/delete_note_ajax', methods=['POST'])
def delete_note_ajax():
    if 'user_id' not in session:
        return jsonify({'success': False, 'message': 'Nie jesteś zalogowany.'}), 401

    data = request.get_json()
    note_id = data.get('note_id')

    user_id = session['user_id']
    note = Note.query.get(note_id)
    if note and note.user_id == user_id:
        db.session.delete(note)
        try:
            db.session.commit()
            notes = Note.query.filter_by(user_id=user_id).all()
            notes_data = [
                {
                    'id': n.id,
                    'content': n.content,
                    'user': {
                        'first_name': n.user.first_name,
                        'last_name': n.user.last_name,
                        'color': n.user.color,
                        'email': n.user.email_address
                    }
                } for n in notes
            ]
            return jsonify({'success': True, 'message': 'Notatka została usunięta.', 'notes': notes_data})
        except Exception as e:
            db.session.rollback()
            app.logger.error(f"Błąd: {e}")
            return jsonify({'success': False, 'message': 'Błąd podczas usuwania notatki.'}), 500
    else:
        return jsonify({'success': False, 'message': 'Notatka nie istnieje lub brak dostępu.'}), 404



@app.route('/delete_all_notes_ajax', methods=['POST'])
def delete_all_notes_ajax():
    if 'user_id' not in session:
        return jsonify({'success': False, 'message': 'Nie jesteś zalogowany.'}), 401

    user_id = session['user_id']
    try:
        deleted_count = Note.query.filter_by(user_id=user_id).delete()
        db.session.commit()
        notes = Note.query.filter_by(user_id=user_id).all()
        notes_data = [{'id': note.id, 'content': note.content} for note in notes]
        return jsonify({'success': True, 'message': f'Usunięto {deleted_count} notatek.', 'notes': notes_data})
    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Błąd: {e}")
        return jsonify({'success': False, 'message': 'Błąd podczas usuwania notatek.'}), 500


# Dodanie funkcji list_routes
@app.route('/routes')
def list_routes():
    import urllib
    output = []
    for rule in app.url_map.iter_rules():
        methods = ','.join(sorted(rule.methods))
        line = urllib.parse.unquote("{:50s} {:20s} {}".format(rule.endpoint, methods, rule))
        output.append(line)
    return "<br>".join(output)


# Trasa "Zapomniałeś hasła" - zmieniona logika
forgot_password_template = '''
<!DOCTYPE html>
<html lang="pl">
<head>
    <meta charset="UTF-8">
    <title>Odzyskiwanie hasła - Ranges</title>
    <link rel="icon" type="image/vnd.microsoft.icon" href="{{ url_for('static', filename='favicon.ico') }}">
    <style>
        body {
            font-family: 'Quantico', sans-serif;
            background-color: #f2f2f2;
            color: #333;
            padding: 20px;
            display: flex;
            justify-content: center;
            align-items: center;
            height: 100vh;
            position: relative;
        }
        .container {
            background-color: #ffffff;
            padding: 30px;
            border-radius: 10px;
            box-shadow: 0 4px 8px rgba(0,0,0,0.2);
            width: 100%;
            max-width: 500px;
            position: relative;
        }
        h2 {
            text-align: center;
            margin-bottom: 20px;
        }
        input, button {
            margin: 10px 0;
            padding: 10px;
            border: none;
            border-radius: 5px;
            transition: 0.3s ease;
            font-size: 16px;
            width: 100%;
            box-sizing: border-box;
        }
        input:focus {
            outline: none;
            box-shadow: 0 0 5px #1f8ef1;
        }
        button {
            background-color: #1f8ef1;
            color: white;
            cursor: pointer;
            transition: background-color 0.3s, transform 0.2s;
            box-shadow: 0 4px 8px rgba(0,0,0,0.2);
            border: 1px solid #1f8ef1;
        }
        button:hover {
            background-color: #0a6db9;
            transform: scale(1.05);
        }
        .flash-message {
            background-color: #f8d7da;
            color: #721c24;
            padding: 10px;
            border-radius: 5px;
            margin: 10px 0;
            text-align: center;
        }
        .flash-message.success {
            background-color: #d4edda;
            color: #155724;
        }
        .flash-message.error {
            background-color: #f8d7da;
            color: #721c24;
        }
        a {
            color: #1f8ef1;
            text-decoration: none;
        }
        a:hover {
            text-decoration: underline;
        }
        .footer {
            color: #888888;
            text-align: center;
            margin-top: 20px;
            font-size: 14px;
        }
    </style>
</head>
<body>
    <div class="container">
        <h2>Odzyskiwanie hasła</h2>
        {% with messages = get_flashed_messages(with_categories=true) %}
            {% if messages %}
                {% for category, message in messages %}
                    <div class="flash-message {{ category }}">
                        {{ message }}
                    </div>
                {% endfor %}
            {% endif %}
        {% endwith %}
        <form method="post">
            <label>Nazwa użytkownika:</label>
            <input type="text" name="username" required>
            <label>Klucz licencyjny:</label>
            <input type="text" name="license_key" required>
            <button type="submit">Weryfikuj</button>
        </form>
        <p><a href="{{ url_for('login') }}">Powrót do logowania</a></p>
        <div class="footer">
            &copy; DigitDrago
        </div>
    </div>
</body>
</html>
'''

@app.route('/forgot_password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        username = request.form.get('username')
        license_key_input = request.form.get('license_key')

        user = User.query.filter_by(username=username).first()
        if user and user.license_key and user.license_key.key == license_key_input:
            # Sprawdzenie czy klucz licencyjny jest ważny i nie wygasł
            license_key = user.license_key
            if license_key.is_revoked:
                flash('Twój klucz licencyjny został unieważniony.', 'error')
                return redirect(url_for('forgot_password'))
            elif license_key.expiration_date < datetime.utcnow():
                flash('Twój klucz licencyjny wygasł.', 'error')
                return redirect(url_for('forgot_password'))
            else:
                # Klucz jest poprawny i aktualny - ustaw verified_user_id i przejdź do resetu hasła
                session['verified_user_id'] = user.id
                return redirect(url_for('reset_password'))
        else:
            flash('Niepoprawny użytkownik lub klucz licencyjny.', 'error')
            return redirect(url_for('forgot_password'))

    return render_template_string(forgot_password_template)


# Szablon resetowania hasła
reset_password_template = '''
<!DOCTYPE html>
<html lang="pl">
<head>
    <meta charset="UTF-8">
    <title>Resetowanie hasła - Ranges</title>
    <link rel="icon" type="image/vnd.microsoft.icon" href="{{ url_for('static', filename='favicon.ico') }}">
    <style>
        body {
            font-family: 'Quantico', sans-serif;
            background-color: #f2f2f2;
            color: #333;
            padding: 20px;
            display: flex;
            justify-content: center;
            align-items: center;
            height: 100vh;
            position: relative;
        }
        .container {
            background-color: #ffffff;
            padding: 30px;
            border-radius: 10px;
            box-shadow: 0 4px 8px rgba(0,0,0,0.2);
            width: 100%;
            max-width: 500px;
            position: relative;
        }
        h2 {
            text-align: center;
            margin-bottom: 20px;
        }
        input, button {
            margin: 10px 0;
            padding: 10px;
            border: none;
            border-radius: 5px;
            transition: 0.3s ease;
            font-size: 16px;
            width: 100%;
            box-sizing: border-box;
        }
        input:focus {
            outline: none;
            box-shadow: 0 0 5px #1f8ef1;
        }
        button {
            background-color: #1f8ef1;
            color: white;
            cursor: pointer;
            transition: background-color 0.3s, transform 0.2s;
            box-shadow: 0 4px 8px rgba(0,0,0,0.2);
            border: 1px solid #1f8ef1;
        }
        button:hover {
            background-color: #0a6db9;
            transform: scale(1.05);
        }
        .flash-message {
            background-color: #f8d7da;
            color: #721c24;
            padding: 10px;
            border-radius: 5px;
            margin: 10px 0;
            text-align: center;
        }
        .flash-message.success {
            background-color: #d4edda;
            color: #155724;
        }
        .flash-message.error {
            background-color: #f8d7da;
            color: #721c24;
        }
        a {
            color: #1f8ef1;
            text-decoration: none;
        }
        a:hover {
            text-decoration: underline;
        }
        .footer {
            color: #888888;
            text-align: center;
            margin-top: 20px;
            font-size: 14px;
        }
    </style>
</head>
<body>
    <div class="container">
        <h2>Resetowanie hasła</h2>
        {% with messages = get_flashed_messages(with_categories=true) %}
            {% if messages %}
                {% for category, message in messages %}
                    <div class="flash-message {{ category }}">
                        {{ message }}
                    </div>
                {% endfor %}
            {% endif %}
        {% endwith %}
        <form method="post">
            <label>Nowe hasło:</label>
            <input type="password" name="new_password" required>
            <button type="submit">Zresetuj hasło</button>
        </form>
        <p><a href="{{ url_for('login') }}">Powrót do logowania</a></p>
        <div class="footer">
            &copy; DigitDrago
        </div>
    </div>
</body>
</html>
'''

@app.route('/reset_password', methods=['GET', 'POST'])
def reset_password():
    if 'verified_user_id' not in session:
        flash('Brak autoryzowanego żądania resetu hasła.', 'error')
        return redirect(url_for('login'))

    if request.method == 'POST':
        new_password = request.form.get('new_password')
        user_id = session['verified_user_id']
        user = db.session.get(User, user_id)
        if user:
            user.set_app_password(new_password)
            db.session.commit()
            flash('Twoje hasło zostało zresetowane. Możesz się teraz zalogować.', 'success')
            session.pop('verified_user_id', None)
            return redirect(url_for('login'))
        else:
            flash('Wystąpił błąd. Spróbuj ponownie.', 'error')
            return redirect(url_for('reset_password'))

    return render_template_string(reset_password_template)



@app.route('/favicon.ico')
def favicon():
    return send_from_directory(os.path.join(app.root_path, 'static'),
                               'favicon.ico', mimetype='image/vnd.microsoft.icon')



# Funkcja wysyłająca przypomnienia o wygaśnięciu klucza licencyjnego
def send_license_expiration_reminders():
    with app.app_context():
        upcoming_expirations = LicenseKey.query.filter(
            LicenseKey.expiration_date <= datetime.utcnow() + timedelta(days=7),
            LicenseKey.expiration_date >= datetime.utcnow(),
            LicenseKey.is_revoked == False
        ).all()
        for license_key in upcoming_expirations:
            users = license_key.users
            for user in users:
                try:
                    send_email(
                        to_email=user.email_address,
                        subject="Przypomnienie o wygaśnięciu klucza licencyjnego",
                        body=f"Drogi {user.first_name},\n\nTwój klucz licencyjny wygasa za mniej niż 7 dni. Prosimy o jego odnowienie.",
                        user=user
                    )
                    app.logger.info(f"Przypomnienie wysłane do: {user.email_address}")
                except Exception as e:
                    app.logger.error(f"Błąd wysyłania przypomnienia do {user.email_address}: {str(e)}")

# Trasa rejestracji
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        try:
            first_name = request.form['first_name']
            last_name = request.form['last_name']
            position = request.form['position']
            username = request.form['username']
            email_address = request.form['email_address']
            email_password = request.form['email_password']
            app_password = request.form['app_password']
            license_key_input = request.form['license_key']
            phone_number = request.form['phone_number'].strip()  # Usunięcie zbędnych spacji

            # Logowanie danych przesłanych w formularzu
            app.logger.debug(f'Received registration data: {request.form}')

            # Dodatkowe oczyszczenie numeru telefonu: usunięcie spacji i myślników
            phone_number = re.sub(r'[\s\-]', '', phone_number)
            app.logger.debug(f'Cleaned phone number: {phone_number}')

            # Walidacja numeru telefonu (serwer-side)
            phone_pattern = re.compile(r'^\+?\d{9,15}$')
            if not phone_pattern.match(phone_number):
                app.logger.error(f"Invalid phone number format: {phone_number}")
                flash('Nieprawidłowy format numeru telefonu. Wprowadź numer w formacie +123456789 lub 123456789.', 'error')
                return redirect(url_for('register'))

            # Sprawdzenie klucza licencyjnego
            license_key = LicenseKey.query.filter_by(key=license_key_input, is_revoked=False).first()
            if not license_key:
                app.logger.error(f"Invalid or revoked license key: {license_key_input}")
                flash('Niepoprawny lub unieważniony klucz licencyjny.', 'error')
                return redirect(url_for('register'))
            elif license_key.expiration_date < datetime.utcnow():
                app.logger.error(f"License key expired: {license_key_input}")
                flash('Klucz licencyjny wygasł.', 'error')
                return redirect(url_for('register'))

            # Sprawdzenie, czy użytkownik już istnieje
            if User.query.filter_by(username=username).first():
                app.logger.error(f"Username already exists: {username}")
                flash('Użytkownik o tej nazwie już istnieje.', 'error')
                return redirect(url_for('register'))
            elif User.query.filter_by(email_address=email_address).first():
                app.logger.error(f"Email address already exists: {email_address}")
                flash('Użytkownik z tym adresem e-mail już istnieje.', 'error')
                return redirect(url_for('register'))
            else:
                # Przypisanie koloru użytkownikowi
                used_colors = [user.color for user in User.query.all()]
                available_colors = [color for color in PASTEL_COLORS if color not in used_colors]
                if available_colors:
                    assigned_color = available_colors[0]
                else:
                    # Jeśli wszystkie kolory są użyte, przypisz losowy kolor z listy
                    import random
                    assigned_color = random.choice(PASTEL_COLORS)

                # Szyfrowanie hasła SMTP
                encrypted_password = fernet.encrypt(email_password.encode()).decode()
                # Haszowanie hasła aplikacyjnego
                hashed_app_password = generate_password_hash(app_password)
                new_user = User(
                    first_name=first_name,
                    last_name=last_name,
                    position=position,
                    username=username,
                    email_address=email_address,
                    email_password=encrypted_password,
                    app_password_hash=hashed_app_password,
                    phone_number=phone_number,
                    license_key=license_key,
                    color=assigned_color  # Przypisanie koloru
                )
                db.session.add(new_user)
                db.session.commit()
                app.logger.info(f"New user registered successfully: {username}")
                flash('Rejestracja zakończona sukcesem. Możesz się teraz zalogować.', 'success')
                return redirect(url_for('login'))
        except Exception as e:
            app.logger.exception("Exception during registration")
            flash('Wystąpił błąd podczas rejestracji. Spróbuj ponownie.', 'error')
            return redirect(url_for('register'))

    # Szablon rejestracji (pozostaje bez zmian)
    register_template = r'''
    <!DOCTYPE html>
    <html lang="pl">
    <head>
        <meta charset="UTF-8">
        <title>Rejestracja - Ranges</title>
        <link rel="icon" type="image/vnd.microsoft.icon" href="{{ url_for('static', filename='favicon.ico') }}">
        <link href="https://fonts.googleapis.com/css2?family=Quantico&display=swap" rel="stylesheet">
        <style>
            /* Stylizacja formularza rejestracji */
            body {
                font-family: 'Quantico', sans-serif;
                background-color: #f2f2f2;
                color: #333;
                padding: 20px;
                display: flex;
                justify-content: center;
                align-items: center;
                height: 100vh;
                position: relative;
            }
            .container {
                background-color: #ffffff;
                padding: 30px;
                padding-top: 100px;
                border-radius: 10px;
                box-shadow: 0 4px 8px rgba(0, 0, 0, 0.2);
                width: 100%;
                max-width: 500px;
                position: relative;
            }
            .header {
                display: flex;
                justify-content: center;
                align-items: center;
                margin-bottom: 20px;
            }
            .header .app-name {
                font-size: 24px;
                font-weight: bold;
                color: #FFD700; /* Złoty kolor neonowy */
                text-shadow: 0 0 10px #FFD700, 0 0 20px #FFD700, 0 0 30px #FFD700;
                text-decoration: none;
            }
            h2 {
                text-align: center;
                margin-bottom: 20px;
                margin-top: 40px;
            }
            input, textarea, select, button {
                margin: 10px 0;
                padding: 10px;
                border: none;
                border-radius: 5px;
                transition: 0.3s ease;
                font-size: 16px;
                width: 100%;
                box-sizing: border-box;
            }
            input:focus, textarea:focus, select:focus {
                outline: none;
                box-shadow: 0 0 5px #1f8ef1;
            }
            button {
                background-color: #1f8ef1;
                color: white;
                cursor: pointer;
                transition: background-color 0.3s, transform 0.2s;
                box-shadow: 0 4px 8px rgba(0, 0, 0, 0.2);
                border: 1px solid #1f8ef1;
            }
            button:hover {
                background-color: #0a6db9;
                transform: scale(1.05);
                box-shadow: 0 8px 16px rgba(0, 0, 0, 0.3);
            }
            button:active {
                animation: buttonBlink 0.2s;
                box-shadow: 0 2px 4px rgba(0, 0, 0, 0.2);
            }
            @keyframes buttonBlink {
                0% { background-color: #0a6db9; }
                50% { background-color: #39FF14; }
                100% { background-color: #0a6db9; }
            }
            .flash-message {
                background-color: #f8d7da;
                color: #721c24;
                padding: 10px;
                border-radius: 5px;
                margin: 10px 0;
                text-align: center;
            }
            .flash-message.success {
                background-color: #d4edda;
                color: #155724;
            }
            .flash-message.error {
                background-color: #f8d7da;
                color: #721c24;
            }
            .flash-message.warning {
                background-color: #fff3cd;
                color: #856404;
            }
            a {
                color: #1f8ef1;
                text-decoration: none;
            }
            a:hover {
                text-decoration: underline;
            }
            /* Zmodyfikowana stopka */
            .footer {
                color: #888888;
                text-align: center;
                margin-top: 20px;
                font-size: 14px;
            }
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <a href="{{ url_for('index') }}" class="app-name">Ranges</a>
            </div>
            <h2>Rejestracja</h2>
            {% with messages = get_flashed_messages(with_categories=true) %}
                {% if messages %}
                    {% for category, message in messages %}
                        <div class="flash-message {{ category }}">
                            {{ message }}
                        </div>
                    {% endfor %}
                {% endif %}
            {% endwith %}
            <form method="post">
                <label>Imię:</label>
                <input type="text" name="first_name" required>

                <label>Nazwisko:</label>
                <input type="text" name="last_name" required>

                <label>Stanowisko:</label>
                <input type="text" name="position" required>

                <label>Nazwa użytkownika:</label>
                <input type="text" name="username" required>

                <label>Adres e-mail:</label>
                <input type="email" name="email_address" required>

                <label>Hasło SMTP:</label>
                <input type="password" name="email_password" required>

                <label>Hasło Aplikacyjne:</label>
                <input type="password" name="app_password" required>

                <label>Numer telefonu:</label>
                <input type="text" name="phone_number" required pattern="^\+?\d{9,15}$" title="Wprowadź prawidłowy numer telefonu">

                <label>Klucz licencyjny:</label>
                <input type="text" name="license_key" required>

                <button type="submit">Zarejestruj się</button>
            </form>
            <p style="text-align: center;">Masz już konto? <a href="{{ url_for('login') }}">Zaloguj się</a></p>
            <!-- Zmodyfikowana stopka -->
            <div class="footer">
                &copy; DigitDrago
            </div>
        </div>
    </body>
    </html>
    '''
    return render_template_string(register_template)


# Trasa logowania
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        app.logger.debug(f"request.form: {request.form}")
        username = request.form.get('username')
        app_password = request.form.get('app_password')
        if not app_password:
            flash('Hasło aplikacyjne jest wymagane.', 'error')
            return redirect(url_for('login'))
        user = User.query.filter_by(username=username).first()
        if user and user.check_app_password(app_password):
            # Sprawdzenie ważności klucza licencyjnego
            license_key = user.license_key
            if license_key.is_revoked:
                flash('Twój klucz licencyjny został unieważniony.', 'error')
                return redirect(url_for('login'))
            elif license_key.expiration_date < datetime.utcnow():
                flash('Twój klucz licencyjny wygasł.', 'error')
                return redirect(url_for('login'))
            elif (license_key.expiration_date - datetime.utcnow()).days <= 7:
                flash('Twój klucz licencyjny wygasa za mniej niż 7 dni. Prosimy o jego odnowienie.', 'warning')

            session['user_id'] = user.id
            session['username'] = user.username
            session['email_address'] = user.email_address
            flash('Zalogowano pomyślnie.', 'success')
            return redirect(url_for('index'))
        else:
            flash('Błędna nazwa użytkownika lub hasło aplikacyjne.', 'error')

    # Zmodyfikowany szablon logowania z dodanym linkiem "Zapomniałeś hasła?"
    login_template = '''
    <!DOCTYPE html>
    <html lang="pl">
    <head>
        <meta charset="UTF-8">
        <title>Logowanie - Ranges</title>
        <link rel="icon" type="image/vnd.microsoft.icon" href="{{ url_for('static', filename='favicon.ico') }}">
        <!-- Dodaj swoje style CSS tutaj -->
        <style>
            /* Przykładowe style CSS */
            body {
                font-family: 'Quantico', sans-serif;
                background-color: #f2f2f2;
                color: #333;
                padding: 20px;
                display: flex;
                justify-content: center;
                align-items: center;
                height: 100vh;
                position: relative;
            }
            .container {
                background-color: #ffffff;
                padding: 30px;
                border-radius: 10px;
                box-shadow: 0 4px 8px rgba(0, 0, 0, 0.2);
                width: 100%;
                max-width: 400px;
                position: relative;
            }
            h2 {
                text-align: center;
                margin-bottom: 20px;
            }
            input, textarea, select, button {
                margin: 10px 0;
                padding: 10px;
                border: none;
                border-radius: 5px;
                transition: 0.3s ease;
                font-size: 16px;
                width: 100%;
                box-sizing: border-box;
            }
            input:focus, textarea:focus, select:focus {
                outline: none;
                box-shadow: 0 0 5px #1f8ef1;
            }
            button {
                background-color: #1f8ef1;
                color: white;
                cursor: pointer;
                transition: background-color 0.3s, transform 0.2s;
                box-shadow: 0 4px 8px rgba(0, 0, 0, 0.2);
                border: 1px solid #1f8ef1;
            }
            button:hover {
                background-color: #0a6db9;
                transform: scale(1.05);
                box-shadow: 0 8px 16px rgba(0, 0, 0, 0.3);
            }
            .flash-message {
                background-color: #f8d7da;
                color: #721c24;
                padding: 10px;
                border-radius: 5px;
                margin: 10px 0;
                text-align: center;
            }
            .flash-message.success {
                background-color: #d4edda;
                color: #155724;
            }
            .flash-message.error {
                background-color: #f8d7da;
                color: #721c24;
            }
            .flash-message.warning {
                background-color: #fff3cd;
                color: #856404;
            }
            a {
                color: #1f8ef1;
                text-decoration: none;
            }
            a:hover {
                text-decoration: underline;
            }
            .footer {
                color: #888888;
                text-align: center;
                margin-top: 20px;
                font-size: 14px;
            }
        </style>
    </head>
    <body>
        <div class="container">
            <h2>Logowanie</h2>
            {% with messages = get_flashed_messages(with_categories=true) %}
                {% if messages %}
                    {% for category, message in messages %}
                        <div class="flash-message {{ category }}">
                            {{ message }}
                        </div>
                    {% endfor %}
                {% endif %}
            {% endwith %}
            <form method="post">
                <label>Nazwa użytkownika:</label>
                <input type="text" name="username" required>

                <label>Hasło Aplikacyjne:</label>
                <input type="password" name="app_password" required>

                <button type="submit">Zaloguj</button>
            </form>
            <p>Nie masz konta? <a href="{{ url_for('register') }}">Zarejestruj się</a></p>
            <!-- Dodany link do odzyskiwania hasła -->
            <p><a href="{{ url_for('forgot_password') }}">Zapomniałeś hasła?</a></p>
            <div class="footer">
                &copy; DigitDrago
            </div>
        </div>
    </body>
    </html>
    '''
    return render_template_string(login_template)



# Trasa wylogowania
@app.route('/logout')
def logout():
    session.clear()
    flash('Wylogowano pomyślnie.', 'success')
    return redirect(url_for('login'))

# Trasa ustawień konta użytkownika
@app.route('/settings', methods=['GET', 'POST'])
def settings():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    user_id = session['user_id']
    user = db.session.get(User, user_id)
    if not user:
        flash('Użytkownik nie istnieje.', 'error')
        return redirect(url_for('login'))
    if request.method == 'POST':
        email_password = request.form.get('email_password')
        app_password = request.form.get('app_password')
        first_name = request.form.get('first_name')
        last_name = request.form.get('last_name')
        position = request.form.get('position')
        phone_number = request.form.get('phone_number')

        # Walidacja numeru telefonu (serwer-side)
        if phone_number:
            phone_pattern = re.compile(r'^\+?\d{9,15}$')
            if not phone_pattern.match(phone_number):
                flash('Nieprawidłowy format numeru telefonu.', 'error')
                return redirect(url_for('settings'))

        if email_password:
            # Szyfrowanie nowego hasła SMTP
            encrypted_password = fernet.encrypt(email_password.encode()).decode()
            user.email_password = encrypted_password
        if app_password:
            # Haszowanie nowego hasła aplikacyjnego
            user.set_app_password(app_password)
        if first_name:
            user.first_name = first_name
        if last_name:
            user.last_name = last_name
        if position:
            user.position = position
        if phone_number:
            user.phone_number = phone_number
        db.session.commit()
        flash('Dane zostały zaktualizowane.', 'success')
        return redirect(url_for('settings'))

    # Szablon ustawień konta
    settings_template = r'''
    <!DOCTYPE html>
    <html lang="pl">
    <head>
        <meta charset="UTF-8">
        <title>Ustawienia konta - Ranges</title>
        <link rel="icon" type="image/vnd.microsoft.icon" href="{{ url_for('static', filename='favicon.ico') }}">
        <link href="https://fonts.googleapis.com/css2?family=Quantico&display=swap" rel="stylesheet">
        <style>
            /* Stylizacja ustawień konta */
            body {
                font-family: 'Quantico', sans-serif;
                background-color: #f2f2f2;
                color: #333;
                padding: 20px;
                display: flex;
                justify-content: center;
                align-items: center;
                min-height: 100vh;
                position: relative;
            }
            .container {
                background-color: #ffffff;
                padding: 30px;
                border-radius: 10px;
                box-shadow: 0 4px 8px rgba(0, 0, 0, 0.2);
                width: 100%;
                max-width: 600px;
                position: relative;
            }
            h2 {
                text-align: center;
                margin-bottom: 20px;
            }
            input, textarea, select, button {
                margin: 10px 0;
                padding: 10px;
                border: none;
                border-radius: 5px;
                transition: 0.3s ease;
                font-size: 16px;
                width: 100%;
                box-sizing: border-box;
            }
            input:focus, textarea:focus, select:focus {
                outline: none;
                box-shadow: 0 0 5px #1f8ef1;
            }
            button {
                background-color: #1f8ef1;
                color: white;
                cursor: pointer;
                transition: background-color 0.3s, transform 0.2s;
                box-shadow: 0 4px 8px rgba(0, 0, 0, 0.2);
                border: 1px solid #1f8ef1;
            }
            button:hover {
                background-color: #0a6db9;
                transform: scale(1.05);
                box-shadow: 0 8px 16px rgba(0, 0, 0, 0.3);
            }
            button:active {
                animation: buttonBlink 0.2s;
                box-shadow: 0 2px 4px rgba(0, 0, 0, 0.2);
            }
            @keyframes buttonBlink {
                0% { background-color: #0a6db9; }
                50% { background-color: #39FF14; }
                100% { background-color: #0a6db9; }
            }
            .flash-message {
                background-color: #f8d7da;
                color: #721c24;
                padding: 10px;
                border-radius: 5px;
                margin: 10px 0;
                text-align: center;
            }
            .flash-message.success {
                background-color: #d4edda;
                color: #155724;
            }
            .flash-message.error {
                background-color: #f8d7da;
                color: #721c24;
            }
            .flash-message.warning {
                background-color: #fff3cd;
                color: #856404;
            }
            a {
                color: #1f8ef1;
                text-decoration: none;
            }
            a:hover {
                text-decoration: underline;
            }
            .user-info {
                position: absolute;
                top: 20px;
                right: 20px;
            }
            /* Zmodyfikowana stopka */
            .footer {
                color: #888888;
                text-align: center;
                margin-top: 20px;
                font-size: 14px;
            }
        </style>
    </head>
    <body>
        <div class="container">
            <h2>Ustawienia konta</h2>
            {% with messages = get_flashed_messages(with_categories=true) %}
                {% if messages %}
                    {% for category, message in messages %}
                        <div class="flash-message {{ category }}">
                            {{ message }}
                        </div>
                    {% endfor %}
                {% endif %}
            {% endwith %}
            <form method="post">
                <label>Imię:</label>
                <input type="text" name="first_name" value="{{ user.first_name }}" required>

                <label>Nazwisko:</label>
                <input type="text" name="last_name" value="{{ user.last_name }}" required>

                <label>Stanowisko:</label>
                <input type="text" name="position" value="{{ user.position }}" required>

                <label>Nazwa użytkownika:</label>
                <input type="text" name="username" value="{{ user.username }}" readonly>

                <label>Adres e-mail:</label>
                <input type="email" name="email_address" value="{{ user.email_address }}" readonly>

                <label>Numer telefonu:</label>
                <input type="text" name="phone_number" value="{{ user.phone_number }}" required pattern="\+?\d{9,15}" title="Wprowadź prawidłowy numer telefonu">

                <label>Hasło SMTP (pozostaw puste, jeśli nie chcesz zmieniać):</label>
                <input type="password" name="email_password">

                <label>Hasło Aplikacyjne (pozostaw puste, jeśli nie chcesz zmieniać):</label>
                <input type="password" name="app_password">

                <button type="submit">Zapisz zmiany</button>
            </form>
            <form method="post" action="{{ url_for('delete_account') }}" onsubmit="return confirm('Czy na pewno chcesz usunąć swoje konto? Ta operacja jest nieodwracalna.');">
                <button type="submit" style="background-color: #ff4d4d; margin-top: 20px;">Usuń konto</button>
            </form>
            <p style="text-align: center; margin-top: 20px;"><a href="{{ url_for('index') }}">Powrót do panelu głównego</a></p>
            <!-- Zmodyfikowana stopka -->
            <div class="footer">
                &copy; DigitDrago
            </div>
        </div>
    </body>
    </html>
    '''
    return render_template_string(settings_template, user=user)


# Trasa usuwania konta
@app.route('/delete_account', methods=['POST'])
def delete_account():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    user_id = session['user_id']
    user = db.session.get(User, user_id)
    if user:
        # Usunięcie notatek użytkownika
        Note.query.filter_by(user_id=user_id).delete()
        # Usunięcie użytkownika
        db.session.delete(user)
        db.session.commit()
        session.clear()
        flash('Twoje konto zostało usunięte.', 'success')
    return redirect(url_for('register'))

# Trasa do dodawania notatek
@app.route('/add_note', methods=['POST'])
def add_note():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    note_content = request.form['note']
    user_id = session['user_id']
    new_note = Note(user_id=user_id, content=note_content)
    db.session.add(new_note)
    db.session.commit()
    flash('Notatka została dodana.', 'success')
    return redirect(url_for('index'))

# Trasa do usuwania notatek
@app.route('/delete_note/<int:index>', methods=['POST'])
def delete_note(index):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    note = Note.query.get(index)
    if note and note.user_id == session['user_id']:
        db.session.delete(note)
        db.session.commit()
        flash('Notatka została usunięta.', 'success')
    else:
        flash('Notatka nie została znaleziona lub nie masz do niej dostępu.', 'error')
    return redirect(url_for('index'))

# Trasa do usuwania wszystkich notatek
@app.route('/delete_all_notes', methods=['POST'])
def delete_all_notes():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    user_id = session['user_id']
    Note.query.filter_by(user_id=user_id).delete()
    db.session.commit()
    flash('Wszystkie notatki zostały usunięte.', 'success')
    return redirect(url_for('index'))

from flask import render_template_string

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


@app.route('/', methods=['GET', 'POST'])
def index():
    if 'user_id' not in session:
        flash('Nie jesteś zalogowany.', 'error')
        return redirect(url_for('login'))

    user_id = session['user_id']
    user = User.query.get(user_id)
    if not user:
        flash('Użytkownik nie istnieje.', 'error')
        return redirect(url_for('login'))

    data = get_data_from_sheet()
    segments = get_unique_segments_with_counts(data)
    notes = Note.query.order_by(Note.id.desc()).all()  # Pobranie wszystkich notatek, najnowsze na górze
    possibilities = get_unique_possibilities_with_companies(data)
    potential_clients = get_potential_clients(data)

    index_template = '''
    <!DOCTYPE html>
    <html lang="pl">
    <head>
        <meta charset="UTF-8">
        <title>Ranges - Panel Główny</title>
        <link rel="icon" href="{{ url_for('static', filename='favicon.ico') }}" type="image/x-icon">
        <link href="https://fonts.googleapis.com/css2?family=Quantico&display=swap" rel="stylesheet">
        <style>
            /* Resetowanie stylów domyślnych */
            * {
                margin: 0;
                padding: 0;
                box-sizing: border-box;
            }
            html, body {
                height: 100%;
            }
            body {
                display: flex;
                flex-direction: column;
                min-height: 100vh;
                font-family: 'Quantico', sans-serif;
                background-color: #f5f5f5;
                color: #333333;
                overflow-x: hidden;
            }
            /* Header */
            .top-header {
                position: fixed;
                top: 0;
                left: 0;
                right: 0;
                height: 60px;
                background-color: #2c3e50;
                box-shadow: 0 2px 4px rgba(0,0,0,0.1);
                z-index: 1001;
                display: flex;
                justify-content: space-between;
                align-items: center;
                padding: 0 20px;
            }
            .header-left {
                display: flex;
                align-items: center;
            }
            .sidebar-toggle-btn {
                background: none;
                border: none;
                cursor: pointer;
                padding: 5px;
                font-size: 24px;
                color: #FFD700;
                display: flex;
                align-items: center;
                margin-top: -2px;
                transition: color 0.3s ease;
            }
            .sidebar-toggle-btn:hover {
                color: #FFC107;
            }
            .header-left .header-title {
                font-size: 24px;
                font-weight: bold;
                color: #ffffff;
                margin-left: 10px;
            }
            .top-header .user-info {
                display: flex;
                align-items: center;
                gap: 15px;
                font-size: 16px;
                color: #cccccc;
            }
            .top-header .user-info a {
                color: #FFD700;
                text-decoration: none;
                transition: color 0.3s ease;
            }
            .top-header .user-info a:hover {
                color: #FFC107;
            }
            /* Wrapper na zawartość */
            .content-wrapper {
                display: flex;
                flex: 1;
                width: 100%;
                margin-top: 60px;
                padding-bottom: 60px;
                position: relative;
                z-index: 1;
            }
            /* Sidebar */
            .sidebar {
                position: fixed;
                top: 60px;
                bottom: 0;
                left: -600px;
                width: 600px;
                background-color: rgba(44, 62, 80, 0.95);
                box-shadow: 2px 0 5px rgba(0,0,0,0.1);
                padding: 20px;
                box-sizing: border-box;
                overflow-y: auto;
                transition: left 0.3s ease;
                z-index: 1000;
                display: flex;
                flex-direction: column;
            }
            .sidebar.active {
                left: 0;
            }
            /* Main Content */
            .main-content {
                flex: 1;
                padding: 20px;
                box-sizing: border-box;
                background-color: #f5f5f5;
                display: flex;
                flex-direction: column;
                overflow-y: auto;
                margin-left: 0;
                transition: margin-left 0.3s ease;
                position: relative;
                z-index: 1;
            }
            .main-content.sidebar-active {
                margin-left: 600px;
            }
            .form-container {
                display: flex;
                flex-direction: column;
                flex: 1;
            }
            h1 {
                color: #333333;
                text-align: center;
                margin-bottom: 20px;
                font-size: 36px;
            }
            /* Flash Messages */
            .flash-message {
                background-color: #e9ecef;
                color: #495057;
                padding: 10px;
                border-radius: 5px;
                margin-bottom: 20px;
                box-shadow: 0 2px 4px rgba(0,0,0,0.1);
                text-align: center;
                display: none;
            }
            .flash-message.show {
                display: block;
            }
            .flash-message.error {
                background-color: #f8d7da;
                color: #721c24;
            }
            .flash-message.success {
                background-color: #d4edda;
                color: #155724;
            }
            .flash-message.warning {
                background-color: #fff3cd;
                color: #856404;
            }
            /* Formularze i elementy */
            label {
                display: block;
                margin-top: 10px;
                font-weight: bold;
                color: #333333;
            }
            input[type="text"], textarea, select, input[type="file"] {
                width: 100%;
                padding: 10px;
                margin-top: 5px;
                border: 1px solid #cccccc;
                border-radius: 5px;
                box-sizing: border-box;
                font-size: 16px;
                background-color: #fafafa;
                color: #333333;
                transition: border-color 0.3s;
            }
            input[type="text"]:focus, textarea:focus, select:focus, input[type="file"]:focus {
                outline: none;
                border-color: #007BFF;
                box-shadow: 0 0 5px rgba(0,123,255,0.5);
            }
            button {
                background-color: #0056b3;
                color: #ffffff;
                padding: 10px 20px;
                border: none;
                border-radius: 5px;
                cursor: pointer;
                font-size: 16px;
                margin-top: 20px;
                transition: background-color 0.3s, transform 0.2s;
                box-shadow: 0 2px 4px rgba(0,0,0,0.2);
                display: flex;
                align-items: center;
            }
            button:hover {
                background-color: #004085;
                transform: scale(1.05);
            }
            button:active {
                transform: scale(0.95);
            }
            .yellow-btn {
                background-color: #DAA520;
                color: #ffffff;
                padding: 8px 12px;
                border: none;
                border-radius: 5px;
                cursor: pointer;
                font-size: 14px;
                margin: 10px 0;
                transition: background-color 0.3s, transform 0.2s;
                width: 100%;
            }
            .yellow-btn:hover {
                background-color: #B8860B;
                transform: scale(1.05);
            }
            .yellow-btn:active {
                transform: scale(0.95);
            }
            .delete-btn {
                background-color: #6c757d;
                color: #ffffff;
                padding: 5px 10px;
                border: none;
                border-radius: 5px;
                cursor: pointer;
                transition: background-color 0.3s, transform 0.2s;
                font-size: 14px;
            }
            .delete-btn:hover {
                background-color: #5a6268;
                transform: scale(1.05);
            }
            .delete-btn:active {
                transform: scale(0.95);
            }
            .edit-btn {
                background-color: #17a2b8;
                color: #ffffff;
                padding: 5px 10px;
                border: none;
                border-radius: 5px;
                cursor: pointer;
                transition: background-color 0.3s, transform 0.2s;
                font-size: 14px;
            }
            .edit-btn:hover {
                background-color: #138496;
                transform: scale(1.05);
            }
            .edit-btn:active {
                transform: scale(0.95);
            }
            .note-section {
                background-color: #ffffff;
                padding: 20px;
                border-radius: 10px;
                box-shadow: 0 2px 4px rgba(0,0,0,0.1);
                margin-top: 30px;
                flex: 0 0 auto;
                max-height: calc(100vh - 160px);
                overflow-y: auto;
                position: relative;
                padding-bottom: 80px;
            }
            .note {
                background-color: #f8f9fa;
                margin: 10px 0;
                padding: 15px;
                border-radius: 5px;
                display: flex;
                flex-direction: column;
                justify-content: space-between;
                box-shadow: 0 1px 3px rgba(0,0,0,0.1);
                position: relative;
            }
            .note-content {
                margin-bottom: 10px;
                white-space: pre-wrap;
                flex: 1;
            }
            .note-footer {
                display: flex;
                justify-content: space-between;
                align-items: center;
                margin-top: 10px;
            }
            .user-name {
                padding: 5px 10px;
                border-radius: 5px;
                color: #333333;
                font-weight: bold;
                background-color: #e2e6ea;
                display: inline-block;
                cursor: pointer;
                transition: background-color 0.3s;
            }
            .user-name:hover {
                background-color: #c8d6e5;
            }
            .note-actions {
                display: flex;
                align-items: center;
                gap: 10px;
            }
            .transfer-note-btn {
                background-color: #000000;
                color: #ffffff;
                padding: 5px 10px;
                border: none;
                border-radius: 5px;
                cursor: pointer;
                transition: background-color 0.3s, transform 0.2s;
            }
            .transfer-note-btn:hover {
                background-color: #333333;
                transform: scale(1.05);
            }
            .transfer-note-btn:active {
                transform: scale(0.95);
            }
            .delete-all-notes-form button {
                background-color: #6c757d;
                color: #ffffff;
                padding: 5px 10px;
                border: none;
                border-radius: 5px;
                cursor: pointer;
                transition: background-color 0.3s, transform 0.2s;
            }
            .delete-all-notes-form button:hover {
                background-color: #5a6268;
                transform: scale(1.05);
            }
            .delete-all-notes-form button:active {
                transform: scale(0.95);
            }
            .segment-list, .possibility-list, .potential-clients-list {
                list-style: none;
                padding-left: 0;
                margin: 0;
            }
            .segment-item, .possibility-item, .potential-client-group {
                display: flex;
                align-items: center;
                margin-bottom: 8px;
            }
            .segment-item input[type="checkbox"],
            .possibility-item input[type="checkbox"],
            .potential-client-group input[type="checkbox"] {
                margin-right: 10px;
                transform: scale(1.2);
                cursor: pointer;
            }
            .segment-label, .possibility-label, .potential-client-group-label {
                font-size: 13px;
                border-bottom: 1px solid rgba(255,255,255,0.2);
                padding-bottom: 5px;
                display: flex;
                justify-content: space-between;
                align-items: center;
                cursor: pointer;
                flex: 1;
                user-select: none;
                color: #ffffff;
            }
            /* Uniemożliwienie kliknięcia na etykietę zaznaczania checkboxa */
            .segment-label,
            .possibility-label,
            .potential-client-group-label {
                pointer-events: auto;
            }
            .segment-label:hover,
            .possibility-label:hover,
            .potential-client-group-label:hover {
                text-decoration: underline;
            }
            .email-item, .company-item, .client-item {
                display: flex;
                align-items: center;
                margin-bottom: 5px;
            }
            .email-item input[type="checkbox"],
            .company-item input[type="checkbox"],
            .client-item input[type="checkbox"] {
                margin-right: 10px;
                transform: scale(1.1);
                cursor: pointer;
            }
            .email-item label,
            .company-item label,
            .client-item label {
                cursor: pointer;
                color: #ffffff;
                font-size: 14px;
                user-select: none;
            }
            /* Zwinięte listy domyślnie */
            .clients-list,
            .email-list,
            .company-list {
                display: none;
                list-style: none;
                padding-left: 20px;
                margin-top: 5px;
                max-height: 300px;
                overflow-y: auto;
            }
            .clients-list.show,
            .email-list.show,
            .company-list.show {
                display: block;
            }
            .toggle-buttons-container {
                display: flex;
                gap: 10px;
                margin-bottom: 20px;
            }
            .toggle-segments-btn, .toggle-possibilities-btn, .toggle-potential-clients-btn {
                background: none;
                border: none;
                cursor: pointer;
                padding: 0;
                display: flex;
                align-items: center;
                justify-content: center;
                transition: transform 0.3s;
            }
            .toggle-segments-btn img, .toggle-possibilities-btn img, .toggle-potential-clients-btn img {
                width: 32px;
                height: 32px;
                transition: transform 0.3s;
            }
            .toggle-segments-btn img.rotate, .toggle-possibilities-btn img.rotate, .toggle-potential-clients-btn img.rotate {
                transform: rotate(180deg);
            }
            .segments-container,
            .possibilities-container,
            .potential-clients-container {
                display: none;
                margin-top: 10px;
            }
            .segments-container.show,
            .possibilities-container.show,
            .potential-clients-container.show {
                display: block;
            }
            #selected-segments, #selected-possibilities, #selected-potential-clients, #selected-users {
                margin-left: 10px;
                font-size: 12px;
                color: #333333;
                max-width: 100%;
                display: flex;
                flex-wrap: wrap;
                gap: 5px;
            }
            .selected-item {
                background-color: #2c3e50;
                color: #ffffff;
                padding: 5px 10px;
                border-radius: 15px;
                display: flex;
                align-items: center;
                font-size: 12px;
                white-space: nowrap;
                overflow: hidden;
                text-overflow: ellipsis;
                border: 1px solid #FFD700;
            }
            .selected-item .remove-item {
                margin-left: 5px;
                cursor: pointer;
                font-weight: bold;
                color: #ffffff;
            }
            .selected-item:hover {
                background-color: #34495e;
            }
            .modal {
                display: none;
                position: fixed;
                z-index: 1002;
                left: 0;
                top: 0;
                width: 100%;
                height: 100%;
                overflow: auto;
                background-color: rgba(0,0,0,0.5);
            }
            .modal-content {
                background-color: #fefefe;
                margin: 10% auto;
                padding: 20px;
                border: 1px solid #888;
                width: 80%;
                max-width: 500px;
                border-radius: 10px;
                box-shadow: 0 5px 15px rgba(0,0,0,0.3);
                position: relative;
            }
            .close-modal {
                color: #aaa;
                float: right;
                font-size: 28px;
                font-weight: bold;
                position: absolute;
                top: 10px;
                right: 20px;
                cursor: pointer;
            }
            .close-modal:hover,
            .close-modal:focus {
                color: black;
                text-decoration: none;
                cursor: pointer;
            }
            .modal-form input[type="text"] {
                width: 100%;
                padding: 10px;
                margin-top: 10px;
                border: 1px solid #cccccc;
                border-radius: 5px;
                box-sizing: border-box;
                font-size: 16px;
                background-color: #fafafa;
                color: #333333;
                transition: border-color 0.3s;
            }
            .modal-form input[type="text"]:focus {
                outline: none;
                border-color: #007BFF;
                box-shadow: 0 0 5px rgba(0,123,255,0.5);
            }
            .modal-form button {
                background-color: #28a745;
                color: #ffffff;
                padding: 10px 20px;
                border: none;
                border-radius: 5px;
                cursor: pointer;
                font-size: 16px;
                margin-top: 20px;
                transition: background-color 0.3s, transform 0.2s;
                width: 100%;
            }
            .modal-form button:hover {
                background-color: #218838;
                transform: scale(1.05);
            }
            .modal-form button:active {
                transform: scale(0.95);
            }
            .dropzone {
                border: 2px dashed #cccccc;
                border-radius: 5px;
                padding: 20px;
                text-align: center;
                color: #999999;
                cursor: pointer;
                transition: background-color 0.3s, border-color 0.3s;
            }
            .dropzone.dragover {
                background-color: #e9ecef;
                border-color: #007BFF;
                color: #333333;
            }
            .attachments-preview {
                display: flex;
                flex-wrap: wrap;
                gap: 10px;
                margin-top: 10px;
            }
            .attachment-item {
                background-color: #f1f1f1;
                padding: 5px 10px;
                border-radius: 5px;
                display: flex;
                align-items: center;
                gap: 5px;
            }
            .attachment-item span {
                font-size: 14px;
            }
            .attachment-item button {
                background: none;
                border: none;
                color: #dc3545;
                font-size: 16px;
                cursor: pointer;
                padding: 0;
            }
            .attachments-count {
                margin-top: 5px;
                font-size: 14px;
                color: #555555;
            }
            .progress-container {
                width: 100%;
                background-color: #f3f3f3;
                border-radius: 5px;
                margin-top: 10px;
                display: none;
            }
            .progress-bar {
                width: 0%;
                height: 20px;
                background-color: #28a745;
                border-radius: 5px;
                text-align: center;
                color: white;
                line-height: 20px;
                transition: width 0.4s ease;
            }
            .spinner {
                border: 4px solid #f3f3f3;
                border-top: 4px solid #007BFF;
                border-radius: 50%;
                width: 24px;
                height: 24px;
                animation: spin 1s linear infinite;
                display: none;
                margin-left: 10px;
            }
            @keyframes spin {
                0% { transform: rotate(0deg); }
                100% { transform: rotate(360deg); }
            }
            .footer {
                background-color: transparent;
                color: #aaaaaa;
                text-align: center;
                padding: 10px;
                font-size: 12px;
                margin-top: auto;
            }
            @media (max-width: 768px) {
                .content-wrapper {
                    flex-direction: column;
                }
                .sidebar {
                    width: 100%;
                    height: auto;
                    left: -100%;
                    bottom: 0;
                }
                .main-content.sidebar-active {
                    margin-left: 0;
                }
                .main-content {
                    padding-top: 70px;
                }
                .note-section {
                    margin: 20px 10px;
                }
                .top-header {
                    justify-content: space-between;
                }
                #selected-segments, #selected-possibilities, #selected-potential-clients, #selected-users {
                    position: static;
                    margin-top: 10px;
                }
            }
        </style>
        <!-- Dodaj CKEditor -->
        <script src="https://cdn.ckeditor.com/ckeditor5/39.0.1/classic/ckeditor.js"></script>
        <script>
            // Funkcje wspólne
            function showFlashMessage(category, message) {
                const flashMessage = document.querySelector(`.flash-message.${category}`);
                if (flashMessage) {
                    flashMessage.textContent = message;
                    flashMessage.classList.add('show');

                    setTimeout(() => {
                        flashMessage.classList.remove('show');
                    }, 5000);
                }
            }

            function showSpinner(spinnerId) {
                const spinner = document.getElementById(spinnerId);
                if (spinner) {
                    spinner.style.display = 'inline-block';
                }
            }

            function hideSpinner(spinnerId) {
                const spinner = document.getElementById(spinnerId);
                if (spinner) {
                    spinner.style.display = 'none';
                }
            }

            function updateNotesList(notes) {
                const notesList = document.querySelector('.note-section ul');
                notesList.innerHTML = '';

                notes.forEach(note => {
                    const li = document.createElement('li');
                    li.className = 'note';
                    li.setAttribute('data-note-id', note.id);
                    li.innerHTML = `
                        <div class="note-content">${escapeHtml(note.content)}</div>
                        <div class="note-footer">
                            <div class="note-actions">
                                <button type="button" class="transfer-note-btn" data-note-content="${escapeHtml(note.content)}">Transfer</button>
                                <button type="button" class="edit-btn" data-note-id="${note.id}" data-note-content="${escapeHtml(note.content)}">Edytuj</button>
                                <form class="delete-note-form" data-note-id="${note.id}">
                                    <button type="submit" class="delete-btn">Usuń</button>
                                    <div class="spinner" id="note-spinner-${note.id}" style="display: none;"></div>
                                </form>
                            </div>
                            <span class="user-name" style="background-color: ${note.user.color};" data-email="${escapeHtml(note.user.email)}">
                                ${escapeHtml(note.user.first_name)} ${escapeHtml(note.user.last_name)}
                            </span>
                        </div>
                    `;
                    notesList.appendChild(li);
                });

                // Reattach event listeners for .user-name
                attachUserNameClickListeners();
            }

            function escapeHtml(text) {
                var map = {
                    '&': '&amp;',
                    '<': '&lt;',
                    '>': '&gt;',
                    '"': '&quot;',
                    "'": '&#039;'
                };
                return text.replace(/[&<>"']/g, function(m) { return map[m]; });
            }

            function transferToMessageField(content) {
                console.log('Transferowanie treści:', content);
                if (window.editor) {
                    window.editor.setData(content);
                    console.log('Treść załadowana do CKEditor.');
                } else {
                    console.log('CKEditor nie jest zainicjalizowany. Aktualizacja pola tekstowego.');
                    document.getElementById('message').value = content;
                }
            }

            function updateSelectedItems() {
                // Segmenty
                const selectedSegments = Array.from(document.querySelectorAll('.segment-item input[type="checkbox"]:checked'))
                    .map(cb => cb.value);
                const selectedSegmentsDiv = document.getElementById('selected-segments');
                selectedSegmentsDiv.innerHTML = '';

                selectedSegments.forEach(segment => {
                    const segmentSpan = document.createElement('span');
                    segmentSpan.className = 'selected-item';
                    segmentSpan.textContent = segment;

                    const removeSpan = document.createElement('span');
                    removeSpan.className = 'remove-item';
                    removeSpan.textContent = '×';
                    removeSpan.setAttribute('data-item', segment);
                    removeSpan.addEventListener('click', function() {
                        const itemToRemove = this.getAttribute('data-item');
                        const checkbox = Array.from(document.querySelectorAll('.segment-item input[type="checkbox"]'))
                            .find(cb => cb.value === itemToRemove);
                        if (checkbox) {
                            checkbox.checked = false;
                            const segmentIndex = checkbox.id.split('-')[1];
                            const emailList = document.getElementById(`emails-${segmentIndex}`);
                            if (emailList) {
                                const emailCheckboxes = emailList.querySelectorAll('input[type="checkbox"]');
                                emailCheckboxes.forEach(emailCb => {
                                    emailCb.checked = false;
                                });
                            }
                        }
                        this.parentElement.remove();
                        updateSelectedItems();
                        updateSelectAllButtons();
                    });

                    segmentSpan.appendChild(removeSpan);
                    selectedSegmentsDiv.appendChild(segmentSpan);
                });

                // Możliwości
                const selectedPossibilities = Array.from(document.querySelectorAll('.possibility-item input[type="checkbox"]:checked'))
                    .map(cb => cb.value);
                const selectedPossibilitiesDiv = document.getElementById('selected-possibilities');
                selectedPossibilitiesDiv.innerHTML = '';

                selectedPossibilities.forEach(possibility => {
                    const possibilitySpan = document.createElement('span');
                    possibilitySpan.className = 'selected-item';
                    possibilitySpan.textContent = possibility;

                    const removeSpan = document.createElement('span');
                    removeSpan.className = 'remove-item';
                    removeSpan.textContent = '×';
                    removeSpan.setAttribute('data-item', possibility);
                    removeSpan.addEventListener('click', function() {
                        const itemToRemove = this.getAttribute('data-item');
                        const checkbox = Array.from(document.querySelectorAll('.possibility-item input[type="checkbox"]'))
                            .find(cb => cb.value === itemToRemove);
                        if (checkbox) {
                            checkbox.checked = false;
                            const possibilityIndex = checkbox.id.split('-')[1];
                            const companyList = document.getElementById(`companies-${possibilityIndex}`);
                            if (companyList) {
                                const companyCheckboxes = companyList.querySelectorAll('input[type="checkbox"]');
                                companyCheckboxes.forEach(companyCb => {
                                    companyCb.checked = false;
                                });
                            }
                        }
                        this.parentElement.remove();
                        updateSelectedItems();
                    });

                    possibilitySpan.appendChild(removeSpan);
                    selectedPossibilitiesDiv.appendChild(possibilitySpan);
                });

                // Potencjalni Klienci
                const selectedPotentialClients = Array.from(document.querySelectorAll('.potential-clients-list .client-item input[type="checkbox"]:checked'))
                    .map(cb => {
                        const label = document.querySelector(`label[for="${cb.id}"]`);
                        if (label) {
                            const text = label.textContent;
                            const companyName = text.split(' (')[0];
                            return { companyName };
                        }
                        return { companyName: cb.value };
                    });

                const selectedPotentialClientsDiv = document.getElementById('selected-potential-clients');
                selectedPotentialClientsDiv.innerHTML = '';

                selectedPotentialClients.forEach(client => {
                    const clientSpan = document.createElement('span');
                    clientSpan.className = 'selected-item';
                    clientSpan.textContent = client.companyName;

                    const removeSpan = document.createElement('span');
                    removeSpan.className = 'remove-item';
                    removeSpan.textContent = '×';
                    removeSpan.setAttribute('data-company', client.companyName);
                    removeSpan.addEventListener('click', function() {
                        const companyToRemove = this.getAttribute('data-company');
                        const checkbox = Array.from(document.querySelectorAll('.potential-clients-list .client-item input[type="checkbox"]'))
                            .find(cb => {
                                const label = document.querySelector(`label[for="${cb.id}"]`);
                                return label && label.textContent.split(' (')[0] === companyToRemove;
                            });
                        if (checkbox) {
                            checkbox.checked = false;
                            // Jeśli wszystkie klienci w grupie są odznaczeni, odznacz również checkbox grupy
                            const groupIndex = checkbox.id.split('-')[2];
                            const groupCheckbox = document.getElementById(`potential-group-${groupIndex}`);
                            const siblingCheckboxes = document.querySelectorAll(`#clients-${groupIndex} .client-item input[type="checkbox"]`);
                            const allUnchecked = Array.from(siblingCheckboxes).every(cb => !cb.checked);
                            if (allUnchecked && groupCheckbox) {
                                groupCheckbox.checked = false;
                            }
                        }
                        this.parentElement.remove();
                        updateSelectedItems();
                    });

                    clientSpan.appendChild(removeSpan);
                    selectedPotentialClientsDiv.appendChild(clientSpan);
                });

                // Wybrane użytkownicy (nowo dodane)
                const selectedUsersDiv = document.getElementById('selected-users');
                selectedUsersDiv.innerHTML = '';

                updateSelectAllButtons();
            }

            // Funkcje do togglowania list
            function toggleSegmentsList(button) {
                var segmentsContainer = document.getElementById('segments-container');
                var img = button.querySelector('img');
                segmentsContainer.classList.toggle('show');
                img.classList.toggle('rotate');
            }

            function togglePossibilitiesList(button) {
                var possibilitiesContainer = document.getElementById('possibilities-container');
                var img = button.querySelector('img');
                possibilitiesContainer.classList.toggle('show');
                img.classList.toggle('rotate');
            }

            function togglePotentialClientsList(button) {
                var potentialClientsContainer = document.getElementById('potential-clients-container');
                var img = button.querySelector('img');
                potentialClientsContainer.classList.toggle('show');
                img.classList.toggle('rotate');
            }

            // Funkcje do zaznaczania/odznaczania wszystkich segmentów
            function toggleSelectAllSegments(button) {
                var segmentCheckboxes = document.querySelectorAll('.segment-item input[type="checkbox"]');
                var allChecked = Array.from(segmentCheckboxes).every(cb => cb.checked);

                segmentCheckboxes.forEach(function(checkbox) {
                    checkbox.checked = !allChecked;
                    handleSegmentChange(checkbox);
                });

                button.textContent = !allChecked ? 'Odznacz wszystkie segmenty' : 'Zaznacz wszystkie segmenty';

                updateSelectedItems();
            }

            // Funkcje do zaznaczania/odznaczania wszystkich możliwości
            function toggleSelectAllPossibilities(button) {
                var possibilityCheckboxes = document.querySelectorAll('.possibility-item input[type="checkbox"]');
                var allChecked = Array.from(possibilityCheckboxes).every(cb => cb.checked);

                possibilityCheckboxes.forEach(function(checkbox) {
                    checkbox.checked = !allChecked;
                    handlePossibilityChange(checkbox);
                });

                button.textContent = !allChecked ? 'Odznacz wszystkie możliwości' : 'Zaznacz wszystkie możliwości';

                updateSelectedItems();
            }

            // Funkcje do zaznaczania/odznaczania wszystkich potencjalnych klientów
            function toggleSelectAllPotentialClients(button) {
                var groupCheckboxes = document.querySelectorAll('.potential-client-group input[type="checkbox"]');
                var clientCheckboxes = document.querySelectorAll('.potential-clients-list .client-item input[type="checkbox"]');
                var allChecked = Array.from(groupCheckboxes).every(cb => cb.checked) && Array.from(clientCheckboxes).every(cb => cb.checked);

                // Zaznacz lub odznacz wszystkie group checkboxes
                groupCheckboxes.forEach(function(groupCheckbox) {
                    groupCheckbox.checked = !allChecked;
                });

                // Zaznacz lub odznacz wszystkie client checkboxes
                clientCheckboxes.forEach(function(clientCheckbox) {
                    clientCheckbox.checked = !allChecked;
                });

                button.textContent = !allChecked ? 'Odznacz wszystkich klientów' : 'Zaznacz wszystkich klientów';

                updateSelectedItems();
            }

            // Funkcje do zaznaczania/odznaczania wszystkich e-maili w segmencie
            function toggleSelectAllEmailsInSegment(emailListId) {
                var emailList = document.getElementById(emailListId);
                var emailCheckboxes = emailList.querySelectorAll('input[type="checkbox"]');
                var toggleBtn = emailList.querySelector('.select-deselect-emails-btn');

                var allChecked = Array.from(emailCheckboxes).every(cb => cb.checked);

                emailCheckboxes.forEach(function(checkbox) {
                    checkbox.checked = !allChecked;
                });

                toggleBtn.textContent = !allChecked ? 'Odznacz Wszystkie' : 'Zaznacz Wszystkie';

                updateSelectedItems();
            }

            // Funkcje do zaznaczania/odznaczania wszystkich firm w możliwości
            function toggleSelectAllCompaniesInPossibility(companyListId) {
                var companyList = document.getElementById(companyListId);
                var companyCheckboxes = companyList.querySelectorAll('input[type="checkbox"]');
                var toggleBtn = companyList.querySelector('.select-deselect-companies-btn');

                var allChecked = Array.from(companyCheckboxes).every(cb => cb.checked);

                companyCheckboxes.forEach(function(checkbox) {
                    checkbox.checked = !allChecked;
                });

                toggleBtn.textContent = !allChecked ? 'Odznacz Wszystkie' : 'Zaznacz Wszystkie';

                updateSelectedItems();
            }

            // Funkcje do rozwijania/zwijania wszystkich list
            function toggleAllSegmentsExpandCollapse(button) {
                var emailLists = document.querySelectorAll('.email-list');
                var allExpanded = Array.from(emailLists).every(list => list.classList.contains('show'));

                emailLists.forEach(list => {
                    if (allExpanded) {
                        list.classList.remove('show');
                    } else {
                        list.classList.add('show');
                    }
                });

                // Zmiana etykiety przycisku w zależności od stanu
                button.textContent = allExpanded ? 'Rozwiń wszystkie segmenty' : 'Zwiń wszystkie segmenty';
            }

            function toggleAllPossibilitiesExpandCollapse(button) {
                var companyLists = document.querySelectorAll('.company-list');
                var allExpanded = Array.from(companyLists).every(list => list.classList.contains('show'));

                companyLists.forEach(list => {
                    if (allExpanded) {
                        list.classList.remove('show');
                    } else {
                        list.classList.add('show');
                    }
                });

                button.textContent = allExpanded ? 'Rozwiń wszystkie możliwości' : 'Zwiń wszystkie możliwości';
            }

            function toggleAllPotentialClientsExpandCollapse(button) {
                var clientLists = document.querySelectorAll('.clients-list');
                var allExpanded = Array.from(clientLists).every(list => list.classList.contains('show'));

                clientLists.forEach(list => {
                    if (allExpanded) {
                        list.classList.remove('show');
                    } else {
                        list.classList.add('show');
                    }
                });

                button.textContent = allExpanded ? 'Rozwiń wszystkich potencjalnych klientów' : 'Zwiń wszystkich potencjalnych klientów';
            }

            // Funkcje do obsługi zmian checkboxów
            function handleSegmentChange(segmentCheckbox) {
                toggleEmailsInSegment(segmentCheckbox);
                updateSelectedItems();
            }

            function handlePossibilityChange(possibilityCheckbox) {
                toggleCompaniesInPossibility(possibilityCheckbox);
                updateSelectedItems();
            }

            function handlePotentialClientGroupChange(groupCheckbox) {
                toggleClientsInGroup(groupCheckbox);
                updateSelectedItems();
            }

            // Funkcje do togglowania e-maili, firm i klientów
            function toggleEmailsInSegment(segmentCheckbox) {
                var segmentIndex = segmentCheckbox.id.split('-')[1];
                var emailList = document.getElementById(`emails-${segmentIndex}`);
                if (emailList) {
                    var emailCheckboxes = emailList.querySelectorAll('input[type="checkbox"]');
                    emailCheckboxes.forEach(function(emailCheckbox) {
                        emailCheckbox.checked = segmentCheckbox.checked;
                    });
                }
            }

            function toggleCompaniesInPossibility(possibilityCheckbox) {
                var possibilityIndex = possibilityCheckbox.id.split('-')[1];
                var companyList = document.getElementById(`companies-${possibilityIndex}`);
                if (companyList) {
                    var companyCheckboxes = companyList.querySelectorAll('input[type="checkbox"]');
                    companyCheckboxes.forEach(function(companyCheckbox) {
                        companyCheckbox.checked = possibilityCheckbox.checked;
                    });
                }
            }

            function toggleClientsInGroup(groupCheckbox) {
                var groupIndex = groupCheckbox.id.split('-')[2];
                var clientsList = document.getElementById(`clients-${groupIndex}`);
                if (clientsList) {
                    var clientCheckboxes = clientsList.querySelectorAll('input[type="checkbox"]');
                    clientCheckboxes.forEach(function(clientCheckbox) {
                        clientCheckbox.checked = groupCheckbox.checked;
                    });
                }
            }

            // Funkcje do obsługi edycji notatek
            document.addEventListener('DOMContentLoaded', function() {
                // Inicjalizacja CKEditor
                ClassicEditor
                    .create(document.querySelector('#message-editor'), {
                        toolbar: ['bold', 'italic', 'underline', 'bulletedList', 'numberedList', 'link']
                    })
                    .then(editor => {
                        window.editor = editor;
                        console.log('CKEditor został zainicjalizowany.');

                        const form = document.getElementById('main-form');
                        form.addEventListener('submit', (event) => {
                            event.preventDefault();

                            // Pobieranie treści edytora
                            const data = editor.getData();
                            document.querySelector('#message').value = data;

                            // Sprawdzanie czy pole wiadomości jest puste
                            const tempElement = document.createElement('div');
                            tempElement.innerHTML = data;
                            const textContent = tempElement.textContent || tempElement.innerText || '';
                            if (textContent.trim() === '') {
                                showFlashMessage('error', 'Pole "Wiadomość" nie może być puste.');
                                editor.editing.view.focus();
                                return;
                            }

                            // Walidacja zaznaczeń segmentów, możliwości i potencjalnych klientów
                            if (!validateParentChildSelection()) {
                                // Jeśli walidacja nie przeszła, to wyświetlamy komunikat (już wyświetlony w funkcji) i nie wysyłamy
                                return;
                            }

                            showSpinner('spinner');
                            const formData = new FormData(form);

                            // Pobieranie zaznaczonych adresów e-mail
                            const emailCheckboxes = document.querySelectorAll('input[name="include_emails"]:checked, input[name="include_potential_emails"]:checked');
                            const emails = Array.from(emailCheckboxes).map(cb => cb.value);

                            // Pobieranie wybranych użytkowników
                            const selectedUserEmails = Array.from(document.querySelectorAll('input[name="selected_users"]'))
                                .map(input => input.value);
                            
                            // Łączenie wszystkich odbiorców
                            const allRecipients = emails.concat(selectedUserEmails);
                            formData.set('recipients', allRecipients.join(','));

                            fetch('{{ url_for("send_message_ajax") }}', {
                                method: 'POST',
                                body: formData,
                                credentials: 'same-origin'
                            })
                            .then(response => response.json())
                            .then(data => {
                                hideSpinner('spinner');
                                if (data.success) {
                                    showFlashMessage('success', data.message);
                                    form.reset();
                                    document.getElementById('attachments-preview').innerHTML = '';
                                    document.getElementById('attachments-count').textContent = `Załączników: 0/{{ max_attachments }}`;
                                    editor.setData('');
                                    updateSelectedItems();
                                } else {
                                    showFlashMessage('error', data.message);
                                }
                            })
                            .catch(error => {
                                console.error('Błąd:', error);
                                hideSpinner('spinner');
                                showFlashMessage('error', 'Wystąpił błąd podczas wysyłania wiadomości.');
                            });
                        });
                    })
                    .catch(error => {
                        console.error('Błąd inicjalizacji CKEditor:', error);
                    });

                // Obsługa kliknięć na etykiety możliwości
                document.querySelectorAll('.possibility-label').forEach(function(label) {
                    label.addEventListener('click', function(event) {
                        var index = this.getAttribute('data-index');
                        toggleCompanyList(index);
                        event.stopPropagation(); // Zapobiega zaznaczeniu checkboxa
                    });
                });

                // Obsługa kliknięć na etykiety segmentów
                document.querySelectorAll('.segment-label').forEach(function(label) {
                    label.addEventListener('click', function(event) {
                        var index = this.getAttribute('data-index');
                        toggleEmailsList(index);
                        event.stopPropagation();
                    });
                });

                // Obsługa kliknięć na etykiety potencjalnych klientów
                document.querySelectorAll('.potential-client-group-label').forEach(function(label) {
                    label.addEventListener('click', function(event) {
                        var index = this.getAttribute('data-index');
                        toggleClientsList(index);
                        event.stopPropagation();
                    });
                });

                // Obsługa otwierania edycji notatek
                document.addEventListener('click', function(event) {
                    if (event.target && event.target.classList.contains('edit-btn')) {
                        const noteId = event.target.getAttribute('data-note-id');
                        const noteContent = event.target.getAttribute('data-note-content');
                        console.log('Kliknięto przycisk Edytuj dla notatki:', noteId);
                        openEditModal(noteId, noteContent);
                    }
                });

                // Obsługa transferu notatek do pola wiadomości
                document.addEventListener('click', function(event) {
                    if (event.target && event.target.classList.contains('transfer-note-btn')) {
                        const noteContent = event.target.getAttribute('data-note-content');
                        console.log('Kliknięto przycisk Transfer. Treść notatki:', noteContent);
                        transferToMessageField(noteContent);
                        showFlashMessage('success', 'Treść notatki została przeniesiona do pola "Wiadomość".');
                    }
                });

                // Obsługa otwierania edycji notatki
                document.querySelectorAll('.edit-btn').forEach(function(button) {
                    button.addEventListener('click', function() {
                        const noteId = this.getAttribute('data-note-id');
                        const noteContent = this.getAttribute('data-note-content');
                        openEditModal(noteId, noteContent);
                    });
                });

                // Obsługa kliknięć na imię i nazwisko użytkownika w notatkach
                document.querySelector('.note-section').addEventListener('click', function(event) {
                    if (event.target && event.target.classList.contains('user-name')) {
                        const userName = event.target.textContent.trim();
                        const userEmail = event.target.getAttribute('data-email');

                        // Sprawdzenie, czy użytkownik jest już dodany
                        const alreadySelected = Array.from(document.querySelectorAll('#selected-users .selected-item'))
                            .some(item => item.getAttribute('data-email') === userEmail);

                        if (!alreadySelected) {
                            // Tworzenie elementu tagu użytkownika
                            const userSpan = document.createElement('span');
                            userSpan.className = 'selected-item';
                            userSpan.setAttribute('data-email', userEmail);
                            userSpan.textContent = userName;

                            // Dodanie przycisku usuwania
                            const removeBtn = document.createElement('span');
                            removeBtn.className = 'remove-item';
                            removeBtn.textContent = '×';
                            removeBtn.addEventListener('click', function() {
                                userSpan.remove();
                            });
                            userSpan.appendChild(removeBtn);

                            // Dodanie ukrytego inputa do formularza
                            const hiddenInput = document.createElement('input');
                            hiddenInput.type = 'hidden';
                            hiddenInput.name = 'selected_users';
                            hiddenInput.value = userEmail;
                            userSpan.appendChild(hiddenInput);

                            // Dodanie tagu do kontenera
                            document.getElementById('selected-users').appendChild(userSpan);
                        }
                    }
                });

                // Obsługa submit dla formularza dodawania notatki
                const addNoteForm = document.getElementById('add-note-form');
                addNoteForm.addEventListener('submit', function(event) {
                    event.preventDefault(); // Zapobiega tradycyjnemu wysłaniu formularza

                    const noteInput = this.querySelector('input[name="note"]');
                    const noteContent = noteInput.value.trim();

                    if (noteContent === '') {
                        showFlashMessage('error', 'Nie można dodać pustej notatki.');
                        return;
                    }

                    // Pokaż spinner
                    showSpinner('note-spinner');

                    // Wyślij AJAX POST request
                    fetch('{{ url_for("add_note_ajax") }}', { // Upewnij się, że używasz url_for dla odpowiedniej ścieżki
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json',
                        },
                        body: JSON.stringify({ note: noteContent }),
                        credentials: 'same-origin' // Umożliwia wysyłanie cookies, jeśli są potrzebne
                    })
                    .then(response => response.json())
                    .then(data => {
                        hideSpinner('note-spinner');
                        if (data.success) {
                            showFlashMessage('success', data.message);
                            updateNotesList(data.notes); // Aktualizuj listę notatek
                            noteInput.value = ''; // Wyczyść pole input
                        } else {
                            showFlashMessage('error', data.message);
                        }
                    })
                    .catch(error => {
                        console.error('Błąd:', error);
                        hideSpinner('note-spinner');
                        showFlashMessage('error', 'Wystąpił błąd podczas dodawania notatki.');
                    });
                });

                // Obsługa otwierania edycji notatki
                // (dublowanie z wcześniejszego event listener jest usunięte)
            });

            // Funkcje do obsługi edycji notatek
            function openEditModal(noteId, currentContent) {
                const modal = document.getElementById('editModal');
                const editForm = document.getElementById('edit-note-form');
                const editInput = document.getElementById('edit-note-input');
                const closeModalBtn = document.getElementById('closeEditModal');

                editInput.value = currentContent;
                editForm.setAttribute('data-note-id', noteId);

                modal.style.display = 'block';

                closeModalBtn.onclick = function() {
                    closeEditModal();
                }

                window.onclick = function(event) {
                    if (event.target == modal) {
                        closeEditModal();
                    }
                }
            }

            function closeEditModal() {
                const modal = document.getElementById('editModal');
                modal.style.display = 'none';
            }

            function editNote(noteId, newContent) {
                showSpinner(`edit-spinner`);

                fetch('{{ url_for("edit_note_ajax") }}', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify({
                        note_id: noteId,
                        new_content: newContent
                    }),
                    credentials: 'same-origin'
                })
                .then(response => response.json())
                .then(data => {
                    hideSpinner(`edit-spinner`);

                    if (data.success) {
                        showFlashMessage('success', data.message);
                        const noteSpan = document.querySelector(`.note[data-note-id="${noteId}"] .note-content`);
                        if (noteSpan) {
                            noteSpan.textContent = data.note.content;
                        }
                        const editBtn = document.querySelector(`.note[data-note-id="${noteId}"] .edit-btn`);
                        if (editBtn) {
                            editBtn.setAttribute('data-note-content', data.note.content);
                        }
                        const transferBtn = document.querySelector(`.note[data-note-id="${noteId}"] .transfer-note-btn`);
                        if (transferBtn) {
                            transferBtn.setAttribute('data-note-content', data.note.content);
                        }
                    } else {
                        showFlashMessage('error', data.message);
                    }

                    closeEditModal();
                })
                .catch(error => {
                    console.error('Błąd podczas edytowania notatki:', error);
                    hideSpinner(`edit-spinner`);
                    showFlashMessage('error', 'Wystąpił błąd podczas edytowania notatki.');
                });
            }

            // Obsługa submit form do edytowania notatki
            document.addEventListener('submit', function(event) {
                if (event.target && event.target.id === 'edit-note-form') {
                    event.preventDefault();
                    const form = event.target;
                    const noteId = form.getAttribute('data-note-id');
                    const newContent = document.getElementById('edit-note-input').value.trim();
                    const spinnerId = `edit-spinner`;

                    if (newContent === '') {
                        showFlashMessage('error', 'Nowa treść notatki nie może być pusta.');
                        return;
                    }

                    editNote(noteId, newContent);
                }
            });

            // Obsługa submit form do usuwania notatek
            document.addEventListener('submit', function(event) {
                if (event.target && event.target.classList.contains('delete-note-form')) {
                    event.preventDefault();
                    const noteId = event.target.getAttribute('data-note-id');
                    const spinnerId = `note-spinner-${noteId}`;

                    showSpinner(spinnerId);

                    fetch('{{ url_for("delete_note_ajax") }}', {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json',
                        },
                        body: JSON.stringify({ note_id: noteId }),
                        credentials: 'same-origin'
                    })
                    .then(response => response.json())
                    .then(data => {
                        hideSpinner(spinnerId);

                        if (data.success) {
                            showFlashMessage('success', data.message);
                            updateNotesList(data.notes);
                            updateSelectedItems();
                        } else {
                            showFlashMessage('error', data.message);
                        }
                    })
                    .catch(error => {
                        console.error('Błąd podczas usuwania notatki:', error);
                        hideSpinner(spinnerId);
                        showFlashMessage('error', 'Wystąpił błąd podczas usuwania notatki.');
                    });
                }
            });

            // Obsługa submit form do usuwania wszystkich notatek
            document.addEventListener('submit', function(event) {
                if (event.target && event.target.id === 'delete-all-notes-form') {
                    event.preventDefault();
                    const spinnerId = 'delete-all-spinner';

                    showSpinner(spinnerId);

                    fetch('{{ url_for("delete_all_notes_ajax") }}', {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json',
                        },
                        body: JSON.stringify({}),
                        credentials: 'same-origin'
                    })
                    .then(response => response.json())
                    .then(data => {
                        hideSpinner(spinnerId);

                        if (data.success) {
                            showFlashMessage('success', data.message);
                            updateNotesList(data.notes);
                            updateSelectedItems();
                        } else {
                            showFlashMessage('error', data.message);
                        }
                    })
                    .catch(error => {
                        console.error('Błąd podczas usuwania wszystkich notatek:', error);
                        hideSpinner(spinnerId);
                        showFlashMessage('error', 'Wystąpił błąd podczas usuwania notatek.');
                    });
                }
            });

            // Funkcje do zarządzania przyciskami "Zaznacz Wszystkie"
            function updateSelectAllButtons() {
                // Aktualizacja przycisków "Zaznacz Wszystkie" dla segmentów
                var selectAllSegmentsBtn = document.getElementById('select-all-segments-btn');
                var segmentCheckboxes = document.querySelectorAll('.segment-item input[type="checkbox"]');
                var allSegmentsChecked = Array.from(segmentCheckboxes).every(cb => cb.checked);
                selectAllSegmentsBtn.textContent = allSegmentsChecked ? 'Odznacz wszystkie segmenty' : 'Zaznacz wszystkie segmenty';

                // Aktualizacja przycisków "Zaznacz Wszystkie" dla możliwości
                var selectAllPossibilitiesBtn = document.getElementById('select-all-possibilities-btn');
                var possibilityCheckboxes = document.querySelectorAll('.possibility-item input[type="checkbox"]');
                var allPossibilitiesChecked = Array.from(possibilityCheckboxes).every(cb => cb.checked);
                selectAllPossibilitiesBtn.textContent = allPossibilitiesChecked ? 'Odznacz wszystkie możliwości' : 'Zaznacz wszystkie możliwości';

                // Aktualizacja przycisków "Zaznacz Wszystkich" dla potencjalnych klientów
                var selectAllPotentialClientsBtn = document.querySelector('.select-deselect-potential-clients-btn');
                var groupCheckboxes = document.querySelectorAll('.potential-client-group input[type="checkbox"]');
                var clientCheckboxes = document.querySelectorAll('.potential-clients-list .client-item input[type="checkbox"]');
                var allPotentialClientsChecked = Array.from(groupCheckboxes).every(cb => cb.checked) && Array.from(clientCheckboxes).every(cb => cb.checked);
                selectAllPotentialClientsBtn.textContent = allPotentialClientsChecked ? 'Odznacz wszystkich klientów' : 'Zaznacz wszystkich klientów';
            }

            function updateEmailToggleButtons() {
                // Aktualizacja przycisków togglingu e-maili w segmentach
                var emailLists = document.querySelectorAll('.email-list');
                emailLists.forEach(function(emailList) {
                    var toggleBtn = emailList.querySelector('.select-deselect-emails-btn');
                    var emailCheckboxes = emailList.querySelectorAll('input[type="checkbox"]');
                    var allChecked = Array.from(emailCheckboxes).every(cb => cb.checked);
                    toggleBtn.textContent = allChecked ? 'Odznacz Wszystkie' : 'Zaznacz Wszystkie';
                });
            }

            function updateCompanyToggleButtons() {
                // Aktualizacja przycisków togglingu firm w możliwościach
                var companyLists = document.querySelectorAll('.company-list');
                companyLists.forEach(function(companyList) {
                    var toggleBtn = companyList.querySelector('.select-deselect-companies-btn');
                    var companyCheckboxes = companyList.querySelectorAll('input[type="checkbox"]');
                    var allChecked = Array.from(companyCheckboxes).every(cb => cb.checked);
                    toggleBtn.textContent = allChecked ? 'Odznacz Wszystkie' : 'Zaznacz Wszystkie';
                });
            }

            // Funkcja do toggle panelu bocznego
            function toggleSidebar(button) {
                var sidebar = document.querySelector('.sidebar');
                sidebar.classList.toggle('active');
                var mainContent = document.querySelector('.main-content');
                mainContent.classList.toggle('sidebar-active');
            }

            // Funkcje do togglowania list e-maili, firm i klientów
            function toggleEmailsList(segmentIndex) {
                var emailList = document.getElementById(`emails-${segmentIndex}`);
                if (emailList) {
                    emailList.classList.toggle('show');
                }
            }

            function toggleCompanyList(possibilityIndex) {
                var companyList = document.getElementById(`companies-${possibilityIndex}`);
                if (companyList) {
                    companyList.classList.toggle('show');
                }
            }

            function toggleClientsList(groupIndex) {
                var clientsList = document.getElementById(`clients-${groupIndex}`);
                if (clientsList) {
                    clientsList.classList.toggle('show');
                }
            }

            // Funkcja walidująca zaznaczenia rodzic-dziecko
            function validateParentChildSelection() {
                // Sprawdzanie segmentów
                const segmentCheckboxes = document.querySelectorAll('.segment-item input[type="checkbox"]');
                for (const segment of segmentCheckboxes) {
                    const segmentIndex = segment.id.split('-')[1];
                    const emailList = document.getElementById(`emails-${segmentIndex}`);
                    if (emailList) {
                        const childEmails = emailList.querySelectorAll('input[type="checkbox"]:checked');
                        // Jeśli są zaznaczone maile, a segment nie jest zaznaczony – błąd
                        if (childEmails.length > 0 && !segment.checked) {
                            showFlashMessage('error', 'Zaznacz etykiety (segmenty)!');
                            return false;
                        }
                    }
                }

                // Sprawdzanie możliwości
                const possibilityCheckboxes = document.querySelectorAll('.possibility-item input[type="checkbox"]');
                for (const possibility of possibilityCheckboxes) {
                    const possibilityIndex = possibility.id.split('-')[1];
                    const companyList = document.getElementById(`companies-${possibilityIndex}`);
                    if (companyList) {
                        const childCompanies = companyList.querySelectorAll('input[type="checkbox"]:checked');
                        // Jeśli są zaznaczone firmy, a możliwość nie jest zaznaczona – błąd
                        if (childCompanies.length > 0 && !possibility.checked) {
                            showFlashMessage('error', 'Zaznacz etykiety (możliwości)!');
                            return false;
                        }
                    }
                }

                // Sprawdzanie potencjalnych klientów
                const groupCheckboxes = document.querySelectorAll('.potential-client-group input[type="checkbox"]');
                for (const group of groupCheckboxes) {
                    const groupIndex = group.id.split('-')[2];
                    const clientsList = document.getElementById(`clients-${groupIndex}`);
                    if (clientsList) {
                        const childClients = clientsList.querySelectorAll('input[type="checkbox"]:checked');
                        // Jeśli są zaznaczeni klienci, a grupa nie jest zaznaczona – błąd
                        if (childClients.length > 0 && !group.checked) {
                            showFlashMessage('error', 'Zaznacz etykiety (potencjalni klienci)!');
                            return false;
                        }
                    }
                }

                return true;
            }

            // Funkcja do obsługi kliknięć na imię i nazwisko użytkownika w notatkach
            function attachUserNameClickListeners() {
                document.querySelectorAll('.user-name').forEach(function(userNameSpan) {
                    userNameSpan.style.cursor = 'pointer';
                    userNameSpan.addEventListener('click', function() {
                        const userName = this.textContent.trim();
                        const userEmail = this.getAttribute('data-email');

                        // Sprawdzenie, czy użytkownik jest już dodany
                        const alreadySelected = Array.from(document.querySelectorAll('#selected-users .selected-item'))
                            .some(item => item.getAttribute('data-email') === userEmail);

                        if (!alreadySelected) {
                            // Tworzenie elementu tagu użytkownika
                            const userSpan = document.createElement('span');
                            userSpan.className = 'selected-item';
                            userSpan.setAttribute('data-email', userEmail);
                            userSpan.textContent = userName;

                            // Dodanie przycisku usuwania
                            const removeBtn = document.createElement('span');
                            removeBtn.className = 'remove-item';
                            removeBtn.textContent = '×';
                            removeBtn.addEventListener('click', function() {
                                userSpan.remove();
                            });
                            userSpan.appendChild(removeBtn);

                            // Dodanie ukrytego inputa do formularza
                            const hiddenInput = document.createElement('input');
                            hiddenInput.type = 'hidden';
                            hiddenInput.name = 'selected_users';
                            hiddenInput.value = userEmail;
                            userSpan.appendChild(hiddenInput);

                            // Dodanie tagu do kontenera
                            document.getElementById('selected-users').appendChild(userSpan);
                        }
                    });
                });
            }
        </script>
    </head>
    <body>
        <!-- Nagłówek -->
        <header class="top-header">
            <div class="header-left">
                <button id="sidebar-toggle" class="sidebar-toggle-btn" onclick="toggleSidebar(this)">&#9776;</button>
                <span class="header-title">Ranges</span>
            </div>
            <div class="header-right">
                <div class="user-info">
                    <span>Witaj, {{ user.username }}!</span> 
                    <a href="{{ url_for('logout') }}">Wyloguj się</a> | 
                    <a href="{{ url_for('settings') }}">Ustawienia konta</a>
                </div>
            </div>
        </header>
        
        <!-- Formularz główny -->
        <form id="main-form" class="main-form" enctype="multipart/form-data">
            <div class="content-wrapper">
                <!-- Panel boczny -->
                <div class="sidebar">
                    <div class="toggle-buttons-container">
                        <!-- Przyciski toggle -->
                        <button type="button" class="toggle-segments-btn" onclick="toggleSegmentsList(this)">
                            <img src="{{ url_for('static', filename='hammer.png') }}" alt="Toggle Segments">
                        </button>

                        <button type="button" class="toggle-possibilities-btn" onclick="togglePossibilitiesList(this)">
                            <img src="{{ url_for('static', filename='greek_key.png') }}" alt="Toggle Possibilities">
                        </button>
                        
                        <!-- Zmiana obrazka na 'money.png' i zmiana etykiety -->
                        <button type="button" class="toggle-potential-clients-btn" onclick="togglePotentialClientsList(this)">
                            <img src="{{ url_for('static', filename='money.png') }}" alt="Toggle Potential Clients">
                        </button>
                    </div>

                    <!-- Kontener segmentów -->
                    <div id="segments-container" class="segments-container">
                        <!-- Przycisk Zaznacz/Odznacz Wszystkie Segmenty -->
                        <button type="button" id="select-all-segments-btn" class="yellow-btn" onclick="toggleSelectAllSegments(this)">Zaznacz wszystkie segmenty</button>

                        <!-- Przycisk Rozwiń/Zwiń Wszystkie Segmenty -->
                        <button type="button" class="yellow-btn" onclick="toggleAllSegmentsExpandCollapse(this)">Rozwiń wszystkie segmenty</button>

                        <!-- Lista segmentów i adresów e-mail -->
                        <ul class="segment-list">
                            {% for segment, counts in segments.items() %}
                                {% set segment_index = loop.index %}
                                <li class="segment-item">
                                    <input type="checkbox" name="segments" value="{{ segment }}" id="segment-{{ segment_index }}" onchange="handleSegmentChange(this)">
                                    <span class="segment-label" data-index="{{ segment_index }}">
                                        {{ segment }} <span class="segment-count">(Polski: {{ counts['Polski'] }}, Zagraniczny: {{ counts['Zagraniczny'] }})</span>
                                    </span>
                                </li>
                                <ul class="email-list" id="emails-{{ segment_index }}">
                                    <!-- Przycisk Zaznacz/Odznacz Wszystkie Adresy w Tym Segmencie -->
                                    <button type="button" class="yellow-btn select-deselect-emails-btn" onclick="toggleSelectAllEmailsInSegment('emails-{{ segment_index }}')">Zaznacz Wszystkie</button>
                                    
                                    {% set emails_companies_polski = get_email_company_pairs_for_segment(data, segment, "Polski") %}
                                    {% set emails_companies_zagraniczny = get_email_company_pairs_for_segment(data, segment, "Zagraniczny") %}
                                    {% for pair in emails_companies_polski %}
                                        <li class="email-item">
                                            <input type="checkbox" name="include_emails" value="{{ pair.email }}" id="email-{{ segment_index }}-polski-{{ loop.index }}">
                                            <label for="email-{{ segment_index }}-polski-{{ loop.index }}">{{ pair.company }} (Polski)</label>
                                        </li>
                                    {% endfor %}
                                    {% for pair in emails_companies_zagraniczny %}
                                        <li class="email-item">
                                            <input type="checkbox" name="include_emails" value="{{ pair.email }}" id="email-{{ segment_index }}-zagraniczny-{{ loop.index }}">
                                            <label for="email-{{ segment_index }}-zagraniczny-{{ loop.index }}">{{ pair.company }} (Zagraniczny)</label>
                                        </li>
                                    {% endfor %}
                                </ul>
                            {% endfor %}
                        </ul>
                    </div>

                    <!-- Kontener możliwości -->
                    <div id="possibilities-container" class="possibilities-container">
                        <!-- Przycisk Zaznacz/Odznacz Wszystkie Możliwości -->
                        <button type="button" id="select-all-possibilities-btn" class="yellow-btn" onclick="toggleSelectAllPossibilities(this)">Zaznacz wszystkie możliwości</button>

                        <!-- Przycisk Rozwiń/Zwiń Wszystkie Możliwości -->
                        <button type="button" class="yellow-btn" onclick="toggleAllPossibilitiesExpandCollapse(this)">Rozwiń wszystkie możliwości</button>

                        <!-- Lista możliwości i firm -->
                        <ul class="possibility-list">
                            {% for possibility, companies in possibilities.items() %}
                                {% set possibility_index = loop.index %}
                                <li class="possibility-item">
                                    <input type="checkbox" name="possibilities" value="{{ possibility }}" id="possibility-{{ possibility_index }}" onchange="handlePossibilityChange(this)">
                                    <span class="possibility-label" data-index="{{ possibility_index }}">
                                        {{ possibility }} <span class="company-count">({{ companies|length }})</span>
                                    </span>
                                </li>
                                <ul class="company-list" id="companies-{{ possibility_index }}">
                                    <!-- Przycisk Zaznacz/Odznacz Wszystkie Firmy w Tej Możliwości -->
                                    <button type="button" class="yellow-btn select-deselect-companies-btn" onclick="toggleSelectAllCompaniesInPossibility('companies-{{ possibility_index }}')">Zaznacz Wszystkie</button>
                    
                                    {% for company in companies %}
                                        <li class="company-item">
                                            <input type="checkbox" name="include_emails" value="{{ company.email }}" id="company-{{ possibility_index }}-{{ loop.index }}">
                                            <label for="company-{{ possibility_index }}-{{ loop.index }}">{{ company.company }}</label>
                                        </li>
                                    {% endfor %}
                                </ul>
                            {% endfor %}
                        </ul>
                    </div>
                    
                    <!-- Kontener potencjalnych klientów -->
                    <div id="potential-clients-container" class="potential-clients-container">
                        <!-- Przycisk Zaznacz/Odznacz Wszystkich Potencjalnych Klientów -->
                        <button type="button" class="yellow-btn select-deselect-potential-clients-btn" onclick="toggleSelectAllPotentialClients(this)">Zaznacz wszystkich klientów</button>
                        
                        <!-- Przycisk Rozwiń/Zwiń Wszystkich Potencjalnych Klientów -->
                        <button type="button" class="yellow-btn" onclick="toggleAllPotentialClientsExpandCollapse(this)">Rozwiń wszystkich potencjalnych klientów</button>

                        <!-- Lista potencjalnych klientów -->
                        <ul class="potential-clients-list">
                            {% for group, clients in potential_clients.items() %}
                                {% set group_index = loop.index %}
                                <li class="potential-client-group">
                                    <input type="checkbox" name="potential_clients" value="{{ group }}" id="potential-group-{{ group_index }}" onchange="handlePotentialClientGroupChange(this)">
                                    <span class="potential-client-group-label" data-index="{{ group_index }}">
                                        {{ group }}
                                    </span>
                                </li>
                                <ul class="clients-list" id="clients-{{ group_index }}">
                                    {% for client in clients %}
                                        <li class="client-item">
                                            <!-- Wyświetlanie tylko nazwy firmy i języka -->
                                            <input type="checkbox" name="include_potential_emails" value="{{ client.email }}" id="client-{{ group_index }}-{{ loop.index }}">
                                            <label for="client-{{ group_index }}-{{ loop.index }}">{{ client.company }} ({{ client.language }})</label>
                                        </li>
                                    {% endfor %}
                                </ul>
                            {% endfor %}
                        </ul>
                    </div>
                </div>

                <!-- Główna treść strony -->
                <div class="main-content">
                    <div class="form-container">
                        <h1>e-Communicator</h1>

                        <div class="flash-message success"></div>
                        <div class="flash-message error"></div>
                        <div class="flash-message warning"></div>

                        <label for="subject">Temat:</label>
                        <input type="text" id="subject" name="subject" required>

                        <label for="message-editor">Wiadomość:</label>
                        <div id="message-editor"></div>
                        <textarea name="message" id="message" style="display: none;"></textarea>

                        <label for="attachments">Załączniki:</label>
                        <input type="file" name="attachments" id="attachments" multiple style="display: none;">
                        <div id="dropzone" class="dropzone">
                            Przeciągnij i upuść pliki tutaj lub kliknij, aby wybrać.
                        </div>
                        <div id="attachments-preview" class="attachments-preview"></div>
                        <div id="attachments-count" class="attachments-count">Załączników: 0/{{ max_attachments }}</div>

                        <label for="language">Wybierz język:</label>
                        <select id="language" name="language" required>
                            <option value="" disabled selected>Wybierz język</option>
                            <option value="Polski">Polski</option>
                            <option value="Zagraniczny">Zagraniczny</option>
                        </select>

                        <div class="button-container" style="display: flex; align-items: flex-start; flex-wrap: wrap; margin-top: 20px;">
                            <button type="submit" id="send-button">Wyślij</button>
                            <div id="selected-segments" style="display: flex; gap: 5px; flex-wrap: wrap;"></div>
                            <div id="selected-possibilities" style="display: flex; gap: 5px; flex-wrap: wrap;"></div>
                            <div id="selected-potential-clients" style="display: flex; gap: 5px; flex-wrap: wrap; margin-left: 10px;"></div>
                            <div id="selected-users" style="display: flex; gap: 5px; flex-wrap: wrap;"></div>
                            <div class="spinner" id="spinner" style="display: none;"></div>
                        </div>
                    </div>
                </div>
            </div>
        </form>

        <!-- Sekcja notatek i modale -->
        <div class="note-section">
            <h3>Notatki</h3>
            <form id="add-note-form">
                <input type="text" name="note" placeholder="Dodaj notatkę..." required>
                <button type="submit">Dodaj notatkę</button>
                <div class="spinner" id="note-spinner" style="display: none;"></div>
            </form>
            <ul>
                {% for note in notes %}
                    <li class="note" data-note-id="{{ note.id }}">
                        <div class="note-content">{{ note.content }}</div>
                        <div class="note-footer">
                            <div class="note-actions">
                                <button type="button" class="transfer-note-btn" data-note-content="{{ note.content|e }}">Transfer</button>
                                <button type="button" class="edit-btn" data-note-id="{{ note.id }}" data-note-content="{{ note.content|e }}">Edytuj</button>
                                <form class="delete-note-form" data-note-id="{{ note.id }}">
                                    <button type="submit" class="delete-btn">Usuń</button>
                                    <div class="spinner" id="note-spinner-{{ note.id }}" style="display: none;"></div>
                                </form>
                            </div>
                            <span class="user-name" style="background-color: {{ note.user.color }};" data-email="{{ note.user.email }}">
                                {{ note.user.first_name }} {{ note.user.last_name }}
                            </span>
                        </div>
                    </li>
                {% endfor %}
            </ul>
            {% if notes %}
                <form class="delete-all-notes-form" id="delete-all-notes-form">
                    <button type="submit">Usuń wszystkie notatki</button>
                    <div class="spinner" id="delete-all-spinner" style="display: none;"></div>
                </form>
            {% endif %}
        </div>

        <!-- Modal do edycji notatki -->
        <div id="editModal" class="modal">
            <div class="modal-content">
                <span id="closeEditModal" class="close-modal">&times;</span>
                <h2>Edytuj Notatkę</h2>
                <form id="edit-note-form" class="modal-form">
                    <label for="edit-note-input">Treść Notatki:</label>
                    <input type="text" id="edit-note-input" name="new_content" required>
                    <button type="submit">Zapisz Zmiany</button>
                    <div class="spinner" id="edit-spinner" style="display: none;"></div>
                </form>
            </div>
        </div>

        <!-- Stopka -->
        <footer class="footer">
            © DigitDrago
        </footer>
    </body>
    </html>
    '''

    return render_template_string(
        index_template,
        user=user,
        segments=segments,
        notes=notes,
        possibilities=possibilities,
        potential_clients=potential_clients,
        get_email_company_pairs_for_segment=get_email_company_pairs_for_segment,
        data=data,
        max_attachments=app.config['MAX_ATTACHMENTS']
    )





if __name__ == '__main__':
    from apscheduler.schedulers.background import BackgroundScheduler
    import atexit

    # Tworzenie katalogu do przechowywania załączników (redundantne, już utworzone wcześniej)
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)

    # Inicjalizacja APScheduler
    scheduler = BackgroundScheduler()
    scheduler.add_job(func=send_license_expiration_reminders, trigger="interval", days=1)
    scheduler.start()

    # Upewnij się, że scheduler zatrzyma się po zakończeniu aplikacji
    atexit.register(lambda: scheduler.shutdown())

    # Uruchomienie aplikacji
    app.run(debug=True, host='0.0.0.0')