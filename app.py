import os
import threading
import logging
from dotenv import load_dotenv
import sys
from flask import Flask, render_template_string, request, redirect, url_for, flash, session, send_from_directory
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
from google.cloud import storage  # Dodany import
import uuid
from datetime import datetime, timedelta, timezone
from werkzeug.security import generate_password_hash, check_password_hash
import re
from random import randint
from flask_mail import Mail, Message
from models import db, User, LicenseKey, Note, VerificationCode
from cryptography.fernet import Fernet
from werkzeug.exceptions import RequestEntityTooLarge
import magic  # Upewnij się, że ta biblioteka jest zainstalowana
import bleach
from flask import jsonify, request
from email.message import EmailMessage
import mimetypes

# Dodaj bieżący katalog do ścieżki Pythona
sys.path.append(os.path.abspath(os.getcwd()))

# Załaduj zmienne środowiskowe z pliku .env
load_dotenv()

# Inicjalizacja aplikacji Flask
app = Flask(__name__)
basedir = os.path.abspath(os.path.dirname(__file__))

# Konfiguracja bazy danych z Heroku (PostgreSQL) lub SQLite
database_url = os.getenv("DATABASE_URL")
if database_url:
    if database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql://", 1)
else:
    # Użyj absolutnej ścieżki do SQLite
    database_url = 'sqlite:///' + os.path.join(basedir, 'users.db')

app.config['SQLALCHEMY_DATABASE_URI'] = database_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Wydrukuj rzeczywistą ścieżkę do bazy danych
if database_url.startswith("sqlite:///"):
    db_path = database_url.replace("sqlite:///", "")
    print(f"Using database at: {db_path}")
else:
    print(f"Używana baza danych: {database_url}")

app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'default_secret_key')
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # Maksymalnie 16 MB na żądanie

# Bezpieczne ustawienia ciasteczek sesji
app.config['SESSION_COOKIE_SECURE'] = False  # Ustaw na True w produkcji
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'

# Inicjalizacja szyfrowania
ENCRYPTION_KEY = os.getenv('ENCRYPTION_KEY').encode()
fernet = Fernet(ENCRYPTION_KEY)

# Konfiguracja Flask-Mail
app.config['MAIL_SERVER'] = 'smtp.office365.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True

# Pobranie MAIL_USERNAME i MAIL_PASSWORD z .env
MAIL_USERNAME = os.getenv('MAIL_USERNAME')
MAIL_PASSWORD_ENCRYPTED = os.getenv('MAIL_PASSWORD')

# Odszyfrowanie MAIL_PASSWORD
try:
    MAIL_PASSWORD = fernet.decrypt(MAIL_PASSWORD_ENCRYPTED.encode()).decode()
except Exception as e:
    print(f"Błąd odszyfrowywania MAIL_PASSWORD: {e}")
    MAIL_PASSWORD = MAIL_PASSWORD_ENCRYPTED  # Jeśli nie jest szyfrowane

# Ustawienie MAIL_USERNAME i MAIL_PASSWORD w konfiguracji Flask
app.config['MAIL_USERNAME'] = MAIL_USERNAME
app.config['MAIL_PASSWORD'] = MAIL_PASSWORD

# Inicjalizacja rozszerzeń
db.init_app(app)
migrate = Migrate(app, db)
mail = Mail(app)

# **Globalny słownik do śledzenia postępu wysyłania e-maili**
email_sending_progress = {}

# Konfiguracja katalogu do przechowywania załączników
UPLOAD_FOLDER = os.path.join(app.root_path, 'uploads')
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # Maksymalny rozmiar załącznika: 16MB

# Tworzenie katalogu do przechowywania załączników
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# Inicjalizacja Google Cloud Storage
storage_client = storage.Client()
GCS_BUCKET = os.getenv('GCS_BUCKET_NAME')  # Upewnij się, że masz zmienną środowiskową z nazwą bucketu
bucket = storage_client.bucket(GCS_BUCKET)

# Dozwolone typy plików
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'pdf', 'doc', 'docx', 'xls', 'xlsx', 'txt', 'zip'}
app.config['MAX_ATTACHMENTS'] = 5


# Konfiguracja Google Sheets API
SCOPES = ['https://www.googleapis.com/auth/spreadsheets.readonly']
SPREADSHEET_ID = os.getenv('SPREADSHEET_ID')  # Umieść w zmiennych środowiskowych
RANGE_NAME = 'data!A1:AA3000'


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
    if mime_type not in allowed_mime_types:
        return False

    return True

def upload_file_to_gcs(file, expiration=3600):
    """
    Przesyła plik do Google Cloud Storage i zwraca signed URL.

    Args:
        file (file object): Obiekt pliku otwarty w trybie binarnym.
        expiration (int, optional): Czas ważności signed URL w sekundach. Domyślnie 3600 sekund (1 godzina).

    Returns:
        str: Signed URL lub False w przypadku błędu.
    """
    try:
        # Pobierz nazwę pliku w bezpieczny sposób
        filename = secure_filename(file.filename)
        
        # Utwórz blob w GCS
        blob = bucket.blob(filename)
        
        # Odczytaj kilka pierwszych bajtów, aby określić typ MIME
        sample = file.read(1024)
        mime_type = magic.from_buffer(sample, mime=True)
        file.seek(0)  # Resetuj wskaźnik pliku do początku
        
        # Prześlij plik z określonym typem MIME
        blob.upload_from_file(file, content_type=mime_type)
        
        # Generuj signed URL z określonym czasem wygaśnięcia
        signed_url = blob.generate_signed_url(expiration=timedelta(seconds=expiration))
        return signed_url
    except Exception as e:
        app.logger.error(f"Nie udało się przesłać pliku {file.filename} do GCS: {e}")
        return False


@app.errorhandler(RequestEntityTooLarge)
def handle_file_too_large(e):
    flash('Przesłany plik jest za duży. Maksymalny rozmiar to 16 MB.', 'error')
    return redirect(url_for('index'))


# Definiowanie szablonu podpisu
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
            
            <!-- Logo DLG i LOGISTICS GROUP umieszczone jeden pod drugim -->
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
                This e-mail is intended solely for the person to whom it is addressed. The contents of this e-mail and any of its attachments contain confidential information, the use or disclosure of which may be restricted. If you are not the addressee of this e-mail or you have received this e-mail by mistake, you may not disclose to other persons, copy or otherwise distribute the contents of this e-mail or its attachments. Please immediately notify the sender of the received e-mail and delete this e-mail and any of its attachments without saving any copies and without disclosing the contents of the e-mail.
            </p>
        </td>
    </tr>
</table>
"""


# Funkcja pobierająca dane z Google Sheets
def get_data_from_sheet():
    """
    Pobiera dane z arkusza Google Sheets w zakresie A1:AH.
    """
    # Pobierz zawartość JSON z zakodowanej zmiennej środowiskowej
    credentials_b64 = os.getenv('GOOGLE_CREDENTIALS_BASE64')
    if credentials_b64:
        credentials_json = base64.b64decode(credentials_b64).decode('utf-8')
        credentials_info = json.loads(credentials_json)
        credentials = service_account.Credentials.from_service_account_info(credentials_info, scopes=SCOPES)
    else:
        raise ValueError("GOOGLE_CREDENTIALS_BASE64 not set in environment variables.")
    
    service = build('sheets', 'v4', credentials=credentials)
    sheet = service.spreadsheets()

    # Ustaw zakres danych na A1:AH, aby obejmować wszystkie kolumny od A do AH
    RANGE_NAME = 'A1:AH'

    result = sheet.values().get(
        spreadsheetId=SPREADSHEET_ID,
        range=RANGE_NAME
    ).execute()
    data = result.get('values', [])

    # Dodaj wypełnienie brakujących kolumn w każdym wierszu
    for i, row in enumerate(data):
        if len(row) < 34:  # AH to 34 kolumny
            row.extend([''] * (34 - len(row)))
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
        "WT Premium", "WT Premium / Rail", "Foreign EU / FCL, LCL",
        "Foreign EU / LCL / FCL / REF",
        "FCL / West / South", "FCL / LCL / FTL / LTL / BALKANS / South",
        "Foreign EU / FTL, LTL, FCL, LCL",
        "Foreign EU / FTL, LTL, FCL, LCL no UA,BY,RU",
        "Foreign EU / FTL, LTL, FCL, LCL from/to UA",
        "Foreign EU / FTL, LTL, FCL, LCL, ADR no UA,BY,RU",
        "Foreign EU / FTL, LTL, FCL, LCL no FR",
        "Foreign EU / FTL, LTL, FCL, LCL + REF",
        "Foreign EU + Scandinavie / FTL, LTL, FCL, LCL",
        "Foreign EU / FTL, LTL", "Foreign EU / FTL, LTL, REF",
        "Foreign EU / FTL +REF +ADR",
        "Foreign EU / FTL, LTL from PL to CZ & EE",
        "FTL / LTL + ADR Poland & Switzerland", "FLT / LTL with lift",
        "FTL K", "LTL", "FTL / LTL K", "LTL K",
        "LTL East Europe", "KOPER", "Only start from Koper",
        "Turkey carriers TIMOKOM", "double-deck car carrier",
        "CARGO Europe / Russia, Turkey, Asia",
        "Foreign EU / only open trailers", "Central Europe",
        "PL REF", "Agency", "DLG", "NON"
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
    """
    Zwraca słownik, gdzie kluczem jest opis możliwości transportowej,
    a wartością lista firm posiadających tę możliwość.
    """
    possibilities = {}
    for row_index, row in enumerate(data):
        # Zakładamy, że nazwa firmy znajduje się w kolumnie U (indeks 20)
        company = row[20].strip() if row[20] else "Nieznana Firma"
        # Zakładamy, że adres e-mail znajduje się w kolumnie R (indeks 17)
        email = row[17].strip() if row[17] else ""

        # Upewnij się, że każdy wiersz ma dokładnie 34 elementy (A1:AH)
        if len(row) != 34:
            print(f"Wiersz {row_index+1} ma niepoprawną liczbę kolumn: {len(row)}")
            continue  # Pomijamy wiersze z niepoprawną liczbą kolumn

        # Iteracja przez kolumny możliwości (Z do AH, indeksy 25 do 33)
        for i in range(25, 34):  # Indeksy 25 do 33 w Pythonie
            possibility = row[i].strip() if row[i] else ''
            if possibility:
                if possibility not in possibilities:
                    possibilities[possibility] = []
                possibilities[possibility].append({'email': email, 'company': company})
                print(f"Znaleziona możliwość '{possibility}' w wierszu {row_index+1} dla firmy '{company}'")
    return possibilities



# Funkcja wysyłająca pojedynczy e-mail
def send_email(to_email, subject, body, user, attachments=None):
    """
    Wysyła e-mail z dynamicznie przekazanymi danymi użytkownika.
    Dołącza załączniki, jeśli są dostępne.
    """
    try:
        # Odszyfruj hasło użytkownika
        email_password_encrypted = user.email_password
        email_password = fernet.decrypt(email_password_encrypted.encode()).decode()

        # Formatowanie numeru telefonu użytkownika
        formatted_phone_number = format_phone_number(user.phone_number)

        # Renderowanie stopki z dynamicznymi danymi użytkownika
        signature = EMAIL_SIGNATURE_TEMPLATE.format(
            first_name=user.first_name,
            last_name=user.last_name,
            position=user.position,
            phone_number=formatted_phone_number,
            email_address=user.email_address
        )

        # Treść wiadomości z poprawionymi odstępami między wierszami i akapitami
        message_body = f'''
        <div style="font-family: Calibri, sans-serif; font-size: 11pt;">
            <style>
                /* Stylowanie akapitów */
                p {{
                    margin: 0;
                    line-height: 1.2; /* Zmniejszona interlinia */
                }}
                p + p {{
                    margin-top: 10px; /* Zmniejszony odstęp między akapitami */
                }}
            </style>
            {body}
        </div>
        '''

        # Łączenie treści wiadomości i stopki
        body_with_signature = f'''
        {message_body}
        {signature}
        '''

        # Utworzenie wiadomości email
        msg = MIMEMultipart()
        msg['Subject'] = subject
        msg['From'] = user.email_address
        msg['To'] = to_email
        msg['Reply-To'] = user.email_address
        msg.attach(MIMEText(body_with_signature, 'html'))

        # Dodanie załączników
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

        # Wysłanie emaila za pomocą smtplib
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



@app.route('/test_email')
def test_email():
    user = User.query.first()  # Wybierz odpowiedniego użytkownika
    if user:
        subject = "Testowy E-mail z Załącznikiem"
        body = "To jest testowy e-mail z załącznikiem."
        # Ścieżka do testowego pliku, upewnij się, że plik istnieje
        test_attachment = os.path.join(app.config['UPLOAD_FOLDER'], 'test_attachment.pdf')
        # Utwórz testowy plik, jeśli nie istnieje
        if not os.path.exists(test_attachment):
            try:
                with open(test_attachment, 'wb') as f:
                    f.write('To jest testowy załącznik.'.encode('utf-8'))
            except Exception as e:
                app.logger.error(f"Nie udało się utworzyć testowego załącznika: {e}")
                flash('Wystąpił błąd podczas tworzenia testowego załącznika.', 'error')
                return redirect(url_for('index'))
        attachment_paths = [test_attachment]
        try:
            send_email(user.email_address, subject, body, user, attachments=attachment_paths)
            flash('Testowy e-mail został wysłany.', 'success')
        except Exception as e:
            flash(f'Wystąpił błąd podczas wysyłania testowego e-maila: {e}', 'error')
    else:
        flash('Nie znaleziono użytkownika do wysłania testowego e-maila.', 'error')
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
    if 'user_id' not in session:
        flash('Nie jesteś zalogowany.', 'error')
        return redirect(url_for('login'))

    user_id = session['user_id']
    user = db.session.get(User, user_id)
    if not user:
        flash('Użytkownik nie istnieje.', 'error')
        return redirect(url_for('login'))

    # Pobierz dane z formularza
    subject = request.form.get('subject')
    message = request.form.get('message')
    language = request.form.get('language')
    segments_selected = request.form.getlist('segments')
    include_emails = request.form.getlist('include_emails')
    attachments = request.files.getlist('attachments')

    # Walidacja danych
    if not subject or not message or not language:
        flash('Proszę wypełnić wszystkie wymagane pola.', 'error')
        return redirect(url_for('index'))

    if not include_emails:
        flash('Proszę wybrać przynajmniej jeden adres e-mail.', 'error')
        return redirect(url_for('index'))

    # Obsługa załączników
    attachment_filenames = []
    for file in attachments:
        if file and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
            file.save(filepath)
            attachment_filenames.append(filepath)
        elif file.filename != '':
            flash(f'Nieprawidłowy typ pliku: {file.filename}', 'error')
            return redirect(url_for('index'))

    # **Nowe: Pobierz dane z arkusza i utwórz mapę adresów e-mail do podsegmentów**
    data = get_data_from_sheet()
    email_subsegment = get_email_subsegment_mapping(data)

    # **Filtruj adresy e-mail zgodnie z wybranym językiem**
    filtered_emails = [email for email in include_emails if email_subsegment.get(email) == language]

    if not filtered_emails:
        flash('Brak adresów e-mail zgodnych z wybranym językiem.', 'error')
        return redirect(url_for('index'))

    try:
        # Wysyłanie e-maili do wybranych adresów
        for email in filtered_emails:
            send_email(
                to_email=email,
                subject=subject,
                body=message,
                user=user,
                attachments=attachment_filenames
            )

        # Usunięcie załączników po wysłaniu
        for filepath in attachment_filenames:
            try:
                os.remove(filepath)
            except Exception as e:
                app.logger.error(f'Nie udało się usunąć załącznika {filepath}: {e}')

        flash('Wiadomość została wysłana pomyślnie.', 'success')
        return redirect(url_for('index'))

    except Exception as e:
        app.logger.error(f'Błąd podczas wysyłania emaila: {e}')
        flash('Wystąpił błąd podczas wysyłania wiadomości.', 'error')
        return redirect(url_for('index'))


# Funkcja asynchroniczna do wysyłania e-maili
def send_emails_async(emails, subject, body, user, attachment_paths=None, task_id=None):
    """
    Funkcja wysyłająca e-maile w tle.
    
    Args:
        emails (list): Lista adresów e-mail do wysłania.
        subject (str): Temat wiadomości.
        body (str): Treść wiadomości w formacie HTML.
        user (User): Obiekt użytkownika wysyłającego wiadomość.
        attachment_paths (list, optional): Lista ścieżek do załączników. Defaults to None.
        task_id (str, optional): Unikalny identyfikator zadania. Defaults to None.
    """
    with app.app_context():
        try:
            app.logger.debug(f"Rozpoczęcie wysyłania e-maili do: {emails}")
            total = len(emails)
            sent = 0
            for email in emails:
                send_email(email, subject, body, user, attachments=attachment_paths)
                sent += 1
                # Aktualizacja postępu
                email_sending_progress[task_id] = {
                    'total': total,
                    'sent': sent
                }
        except Exception as e:
            app.logger.error(f"Błąd podczas wysyłania e-maili: {str(e)}")
        finally:
            # Usunięcie postępu po zakończeniu
            email_sending_progress.pop(task_id, None)
            # Usuwanie załączników po wysłaniu wszystkich e-maili
            if attachment_paths:
                for file_path in attachment_paths:
                    try:
                        if os.path.exists(file_path):
                            os.remove(file_path)
                            app.logger.info(f"Usunięto załącznik: {file_path}")
                        else:
                            app.logger.error(f"Nie udało się usunąć załącznika {file_path}: Plik nie istnieje.")
                    except Exception as e:
                        app.logger.error(f"Nie udało się usunąć załącznika {file_path}: {e}")

@app.route('/email_progress/<task_id>')
def email_progress(task_id):
    """
    Trasa zwracająca aktualny postęp wysyłania e-maili.

    Args:
        task_id (str): Unikalny identyfikator zadania.

    Returns:
        JSON: Procentowy postęp wysyłania.
    """
    progress = email_sending_progress.get(task_id, None)
    if progress:
        percentage = (progress['sent'] / progress['total']) * 100
        return jsonify({'percentage': percentage})
    else:
        # Jeśli zadanie nie istnieje lub zostało ukończone
        return jsonify({'percentage': 100})


# Funkcja formatowania numeru telefonu
def format_phone_number(phone_number):
    """
    Formatuje numer telefonu, dodając spacje po kodzie kraju i co trzy cyfry.
    Przykład: '+48786480887' -> '+48 786 480 887'
    """
    # Sprawdzenie, czy numer zaczyna się od '+48' i ma dokładnie 12 znaków (+48 + 9 cyfr)
    if phone_number.startswith('+48') and len(phone_number) == 12 and phone_number[3:].isdigit():
        return f"{phone_number[:3]} {phone_number[3:6]} {phone_number[6:9]} {phone_number[9:]}"
    else:
        # Jeśli numer nie pasuje do oczekiwanego formatu, zwróć go bez zmian
        return phone_number

# Funkcja wysyłająca e-maile z kodem weryfikacyjnym

def send_verification_email(user, code):
    """
    Wysyła e-mail z kodem weryfikacyjnym do użytkownika.
    """
    subject = "Kod weryfikacyjny do resetowania hasła"
    sender = app.config['MAIL_USERNAME']
    recipients = [user.email_address]
    # Tworzenie HTML wiadomości z mniejszym odstępem między wierszami
    body = f"""
    <div style="line-height: 0.8; font-family: Arial, sans-serif;">
        <p style="margin: 2px 0;">Cześć {user.first_name},</p>
        <p style="margin: 2px 0;">Twój kod weryfikacyjny to: <strong>{code}</strong></p>
        <p style="margin: 2px 0;">Kod jest ważny przez 15 minut.</p>
        <p style="margin: 2px 0;">Pozdrawiam,<br>Zespół Ranges</p>
    </div>
    """

    msg = Message(subject=subject, sender=sender, recipients=recipients, html=body)
    try:
        mail.send(msg)
        app.logger.info(f"E-mail weryfikacyjny wysłany do {user.email_address}.")
        return True
    except Exception as e:
        app.logger.error(f"Błąd podczas wysyłania e-maila do {user.email_address}: {e}")
        return False

@app.route('/send_email_ajax', methods=['POST'])
def send_email_ajax():
    if 'user_id' not in session:
        return jsonify({'success': False, 'message': 'Nie jesteś zalogowany.'}), 401

    user_id = session['user_id']
    user = db.session.get(User, user_id)
    if not user:
        return jsonify({'success': False, 'message': 'Użytkownik nie istnieje.'}), 404

    # Pobranie danych z formularza
    subject = request.form.get('subject')
    message = request.form.get('message')
    language = request.form.get('language')
    segments_selected = request.form.getlist('segments')
    include_emails = request.form.getlist('include_emails')
    attachments = request.files.getlist('attachments')

    # Walidacja wymaganych pól
    if not subject or not message or not language:
        return jsonify({'success': False, 'message': 'Proszę wypełnić wszystkie wymagane pola.'}), 400

    # Filtracja i walidacja emaili
    valid_emails = [email.strip() for email in include_emails if email.strip()]
    if not valid_emails:
        return jsonify({'success': False, 'message': 'Proszę wybrać przynajmniej jeden adres e-mail.'}), 400

    # Obsługa załączników
    attachment_filenames = []
    for file in attachments:
        if file and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
            file.save(filepath)
            attachment_filenames.append(filepath)
        elif file.filename != '':
            return jsonify({'success': False, 'message': f'Nieprawidłowy typ pliku: {file.filename}'}), 400

    try:
        # Konfiguracja SMTP
        smtp_server = 'smtp.example.com'  # Zmień na swój serwer SMTP
        smtp_port = 587  # Typowy port dla TLS
        smtp_username = 'your_email@example.com'  # Twoja nazwa użytkownika SMTP
        smtp_password = 'your_email_password'  # Twoje hasło SMTP

        # Utworzenie wiadomości email
        msg = EmailMessage()
        msg['Subject'] = subject
        msg['From'] = smtp_username
        msg['To'] = ', '.join(valid_emails)
        msg.set_content(message, subtype='html')

        # Dodanie załączników
        for filepath in attachment_filenames:
            with open(filepath, 'rb') as f:
                file_data = f.read()
                file_type = mimetypes.guess_type(filepath)[0] or 'application/octet-stream'
                maintype, subtype = file_type.split('/', 1)
                msg.add_attachment(file_data, maintype=maintype, subtype=subtype, filename=os.path.basename(filepath))

        # Wysłanie emaila
        with smtplib.SMTP(smtp_server, smtp_port) as server:
            server.starttls()
            server.login(smtp_username, smtp_password)
            server.send_message(msg)

        # Usunięcie załączników po wysłaniu
        for filepath in attachment_filenames:
            try:
                os.remove(filepath)
            except Exception as e:
                app.logger.error(f'Nie udało się usunąć załącznika {filepath}: {e}')

        return jsonify({'success': True, 'message': 'Wiadomość została wysłana pomyślnie.'}), 200

    except Exception as e:
        app.logger.error(f'Błąd podczas wysyłania emaila: {e}')
        return jsonify({'success': False, 'message': 'Wystąpił błąd podczas wysyłania wiadomości.'}), 500


@app.route('/send_message_ajax', methods=['POST'])
def send_message_ajax():
    if 'user_id' not in session:
        return jsonify({'success': False, 'message': 'Nie jesteś zalogowany.'}), 401

    user_id = session['user_id']
    user = db.session.get(User, user_id)
    if not user:
        return jsonify({'success': False, 'message': 'Użytkownik nie istnieje.'}), 404

    # Pobranie danych z formularza
    subject = request.form.get('subject')
    message = request.form.get('message')
    language = request.form.get('language')
    segments_selected = request.form.getlist('segments')
    include_emails = request.form.getlist('include_emails')
    attachments = request.files.getlist('attachments')

    # Walidacja wymaganych pól
    if not subject or not message or not language:
        return jsonify({'success': False, 'message': 'Proszę wypełnić wszystkie wymagane pola.'}), 400

    if not include_emails:
        return jsonify({'success': False, 'message': 'Proszę wybrać przynajmniej jeden adres e-mail.'}), 400

    # Obsługa załączników
    attachment_filenames = []
    for file in attachments:
        if file and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
            file.save(filepath)
            attachment_filenames.append(filepath)
        elif file.filename != '':
            return jsonify({'success': False, 'message': f'Nieprawidłowy typ pliku: {file.filename}'}), 400

    # **Nowe: Pobierz dane z arkusza i utwórz mapę adresów e-mail do podsegmentów**
    data = get_data_from_sheet()
    email_subsegment = get_email_subsegment_mapping(data)

    # **Filtruj adresy e-mail zgodnie z wybranym językiem**
    filtered_emails = [email for email in include_emails if email_subsegment.get(email) == language]

    if not filtered_emails:
        return jsonify({'success': False, 'message': 'Brak adresów e-mail zgodnych z wybranym językiem.'}), 400

    try:
        # Wysyłanie e-maili do wybranych adresów
        for email in filtered_emails:
            send_email(
                to_email=email,
                subject=subject,
                body=message,
                user=user,
                attachments=attachment_filenames
            )

        # Usunięcie załączników po wysłaniu
        for filepath in attachment_filenames:
            try:
                os.remove(filepath)
            except Exception as e:
                app.logger.error(f'Nie udało się usunąć załącznika {filepath}: {e}')

        return jsonify({'success': True, 'message': 'Wiadomość została wysłana pomyślnie.'}), 200

    except Exception as e:
        app.logger.error(f'Błąd podczas wysyłania emaila: {e}')
        return jsonify({'success': False, 'message': 'Wystąpił błąd podczas wysyłania wiadomości.'}), 500



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
            notes_data = [{'id': note.id, 'content': note.content} for note in notes]
            return jsonify({'success': True, 'message': 'Notatka została dodana.', 'notes': notes_data})
        except Exception as e:
            db.session.rollback()
            app.logger.error(f"Nie udało się dodać notatki: {e}")
            return jsonify({'success': False, 'message': 'Wystąpił błąd podczas dodawania notatki.'}), 500
    else:
        return jsonify({'success': False, 'message': 'Nie można dodać pustej notatki.'}), 400



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
            # Pobranie zaktualizowanej listy notatek
            notes = Note.query.filter_by(user_id=user_id).all()
            notes_data = [{'id': note.id, 'content': note.content} for note in notes]
            return jsonify({'success': True, 'message': 'Notatka została usunięta.', 'notes': notes_data})
        except Exception as e:
            db.session.rollback()
            app.logger.error(f"Nie udało się usunąć notatki: {e}")
            return jsonify({'success': False, 'message': 'Wystąpił błąd podczas usuwania notatki.'}), 500
    else:
        return jsonify({'success': False, 'message': 'Notatka nie została znaleziona lub nie masz do niej dostępu.'}), 404



@app.route('/delete_all_notes_ajax', methods=['POST'])
def delete_all_notes_ajax():
    if 'user_id' not in session:
        return jsonify({'success': False, 'message': 'Nie jesteś zalogowany.'}), 401

    user_id = session['user_id']
    try:
        # Usunięcie wszystkich notatek użytkownika
        deleted_count = Note.query.filter_by(user_id=user_id).delete()
        db.session.commit()
        # Pobranie zaktualizowanej listy notatek (powinna być pusta)
        notes = Note.query.filter_by(user_id=user_id).all()
        notes_data = [{'id': note.id, 'content': note.content} for note in notes]
        return jsonify({'success': True, 'message': f'Usunięto {deleted_count} notatek.', 'notes': notes_data})
    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Błąd podczas usuwania wszystkich notatek: {e}")
        return jsonify({'success': False, 'message': 'Wystąpił błąd podczas usuwania notatek.'}), 500

from flask import jsonify

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
        return jsonify({'success': False, 'message': 'Notatka nie została znaleziona lub nie masz do niej dostępu.'}), 404

    try:
        note.content = new_content.strip()
        db.session.commit()
        return jsonify({'success': True, 'message': 'Notatka została zaktualizowana.', 'note': {'id': note.id, 'content': note.content}})
    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Nie udało się zaktualizować notatki: {e}")
        return jsonify({'success': False, 'message': 'Wystąpił błąd podczas aktualizacji notatki.'}), 500



# Trasa "Zapomniałeś hasła"
@app.route('/forgot_password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        username = request.form.get('username')
        user = User.query.filter_by(username=username).first()
        if user:
            # Generowanie 6-cyfrowego kodu
            code = f"{randint(100000, 999999)}"
            expiration_time = datetime.utcnow() + timedelta(minutes=15)

            # Zapisanie kodu w bazie danych
            verification_code = VerificationCode(user_id=user.id, code=code, expiration_time=expiration_time)
            db.session.add(verification_code)
            db.session.commit()

            # Wysłanie e-maila z kodem weryfikacyjnym
            if send_verification_email(user, code):
                flash('Kod weryfikacyjny został wysłany na Twój adres e-mail.', 'success')
                session['reset_user_id'] = user.id
                return redirect(url_for('verify_email_code'))
            else:
                flash('Wystąpił błąd podczas wysyłania e-maila. Skontaktuj się z administratorem.', 'error')
                return redirect(url_for('forgot_password'))
        else:
            flash('Użytkownik o podanej nazwie nie istnieje.', 'error')
            return redirect(url_for('forgot_password'))

    # Szablon "Zapomniałeś hasła"
    forgot_password_template = '''
    <!DOCTYPE html>
    <html lang="pl">
    <head>
        <meta charset="UTF-8">
        <title>Odzyskiwanie hasła - Ranges</title>
        <link rel="icon" type="image/vnd.microsoft.icon" href="{{ url_for('static', filename='favicon.ico') }}">
        <style>
            /* Dodaj swoje style CSS tutaj */
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
                <button type="submit">Wyślij kod weryfikacyjny</button>
            </form>
            <p><a href="{{ url_for('login') }}">Powrót do logowania</a></p>
            <div class="footer">
                &copy; DigitDrago
            </div>
        </div>
    </body>
    </html>
    '''
    return render_template_string(forgot_password_template)



# Trasa weryfikacji kodu e-mail
@app.route('/verify_email_code', methods=['GET', 'POST'])
def verify_email_code():
    if 'reset_user_id' not in session:
        flash('Brak autoryzowanego żądania resetu hasła.', 'error')
        return redirect(url_for('login'))

    if request.method == 'POST':
        code = request.form.get('code')
        user_id = session['reset_user_id']
        verification_code = VerificationCode.query.filter_by(user_id=user_id, code=code).first()
        if verification_code and verification_code.expiration_time >= datetime.utcnow():
            # Kod jest poprawny i nie wygasł
            session['verified_user_id'] = user_id
            # Usunięcie kodu z bazy danych
            db.session.delete(verification_code)
            db.session.commit()
            return redirect(url_for('reset_password'))
        else:
            flash('Niepoprawny lub wygasły kod weryfikacyjny.', 'error')
            return redirect(url_for('verify_email_code'))

    # Szablon wprowadzania kodu weryfikacyjnego z e-maila
    verify_email_code_template = '''
    <!DOCTYPE html>
    <html lang="pl">
    <head>
        <meta charset="UTF-8">
        <title>Weryfikacja kodu E-mail - Ranges</title>
        <link rel="icon" type="image/vnd.microsoft.icon" href="{{ url_for('static', filename='favicon.ico') }}">
        <style>
            /* Dodaj swoje style CSS tutaj */
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
            <h2>Weryfikacja kodu E-mail</h2>
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
                <label>Wprowadź kod weryfikacyjny:</label>
                <input type="text" name="code" required>
                <button type="submit">Zweryfikuj kod</button>
            </form>
            <p><a href="{{ url_for('login') }}">Powrót do logowania</a></p>
            <div class="footer">
                &copy; DigitDrago
            </div>
        </div>
    </body>
    </html>
    '''
    return render_template_string(verify_email_code_template)

@app.route('/favicon.ico')
def favicon():
    return send_from_directory(os.path.join(app.root_path, 'static'),
                               'favicon.ico', mimetype='image/vnd.microsoft.icon')
# Trasa resetowania hasła
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
            # Usunięcie sesji resetu
            session.pop('reset_user_id', None)
            session.pop('verified_user_id', None)
            return redirect(url_for('login'))
        else:
            flash('Wystąpił błąd. Spróbuj ponownie.', 'error')
            return redirect(url_for('reset_password'))

    # Szablon resetowania hasła
    reset_password_template = '''
    <!DOCTYPE html>
    <html lang="pl">
    <head>
        <meta charset="UTF-8">
        <title>Resetowanie hasła - Ranges</title>
        <link rel="icon" type="image/vnd.microsoft.icon" href="{{ url_for('static', filename='favicon.ico') }}">
        <style>
            /* Dodaj swoje style CSS tutaj */
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
    return render_template_string(reset_password_template)



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
                    license_key=license_key
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

    # Szablon rejestracji
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
        return redirect(url_for('login'))

    user_id = session['user_id']
    user = User.query.get(user_id)
    if not user:
        flash('Użytkownik nie istnieje.', 'error')
        return redirect(url_for('login'))

    data = get_data_from_sheet()
    segments = get_unique_segments_with_counts(data)
    notes = Note.query.filter_by(user_id=user_id).all()

    # Pobranie możliwości transportowych z informacją o języku
    possibilities = get_unique_possibilities_with_companies(data)

    # Szablon główny z obsługą AJAX dla notatek i wysyłania emaili
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
                left: -600px; /* Zwiększona szerokość sidebaru */
                width: 600px; /* Zwiększona szerokość sidebaru */
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
                margin-left: 600px; /* Dopasowana do szerokości sidebaru */
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
                background-color: #DAA520; /* Ciemnożółty kolor */
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
                background-color: #B8860B; /* Ciemniejszy odcień żółci */
                transform: scale(1.05);
            }
            .yellow-btn:active {
                transform: scale(0.95);
            }
            /* Styl dla przycisku "Usuń" */
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
            /* Styl dla przycisku "Edytuj" */
            .edit-btn {
                background-color: #17a2b8; /* Ciemnoniebieski */
                color: #ffffff; /* Biały tekst */
                padding: 5px 10px;
                border: none;
                border-radius: 5px;
                cursor: pointer;
                transition: background-color 0.3s, transform 0.2s;
                font-size: 14px;
            }
            .edit-btn:hover {
                background-color: #138496; /* Jaśniejszy niebieski */
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
                padding: 10px;
                border-radius: 5px;
                display: flex;
                justify-content: space-between;
                align-items: center;
                box-shadow: 0 1px 3px rgba(0,0,0,0.1);
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
            .segment-list {
                list-style: none;
                padding: 0;
                margin: 0;
            }
            .segment-item {
                display: flex;
                align-items: center;
                margin-bottom: 8px; /* Umiarkowany odstęp */
            }
            .segment-item input[type="checkbox"] {
                margin-right: 10px;
                transform: scale(1.2);
            }
            .segment-label {
                font-size: 13px; /* Przywrócenie czytelnego rozmiaru czcionki */
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
            /* Container for toggle buttons placed side by side */
            .toggle-buttons-container {
                display: flex;
                gap: 10px;
                margin-bottom: 20px;
            }
            /* Toggle Segments Button */
            .toggle-segments-btn, .toggle-possibilities-btn {
                background: none;
                border: none;
                cursor: pointer;
                padding: 0;
                display: flex;
                align-items: center;
                justify-content: center;
                transition: transform 0.3s;
            }
            .toggle-segments-btn img, .toggle-possibilities-btn img {
                width: 32px;
                height: 32px;
                transition: transform 0.3s;
            }
            .toggle-segments-btn img.rotate, .toggle-possibilities-btn img.rotate {
                transform: rotate(180deg);
            }
            /* Kontener segmentów */
            .segments-container {
                display: none;
                margin-top: 10px;
            }
            .segments-container.show {
                display: block;
            }
            /* Kontener możliwości */
            .possibilities-container {
                display: none;
                margin-top: 10px;
            }
            .possibilities-container.show {
                display: block;
            }
            /* Lista możliwości */
            .possibility-list {
                list-style: none;
                padding: 0;
                margin: 0;
            }
            .possibility-item {
                display: flex;
                align-items: center;
                margin-bottom: 8px; /* Umiarkowany odstęp */
            }
            .possibility-item input[type="checkbox"] {
                margin-right: 10px;
                transform: scale(1.2);
            }
            .possibility-label {
                font-size: 13px; /* Przywrócenie czytelnego rozmiaru czcionki */
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
            /* Lista firm w możliwości */
            .company-list {
                list-style: none;
                padding-left: 20px;
                margin-top: 10px;
                display: none;
                max-height: 300px;
                overflow-y: auto;
            }
            .company-list.show {
                display: block;
            }
            .company-item {
                display: flex;
                align-items: center;
                margin-bottom: 5px;
            }
            .company-item input[type="checkbox"] {
                margin-right: 10px;
                transform: scale(1.1);
            }
            .company-item label {
                flex: 1;
                cursor: pointer;
                color: #ffffff;
                display: flex;
                align-items: center;
                justify-content: space-between;
                font-size: 12px; /* Umiarkowany rozmiar czcionki */
            }
            /* Styl dla przycisku "Zaznacz Wszystkie" w firmach */
            .select-deselect-companies-btn {
                background-color: #DAA520; /* Ciemnożółty kolor */
                color: #ffffff;
                padding: 5px 10px;
                border: none;
                border-radius: 5px;
                cursor: pointer;
                font-size: 14px;
                margin-bottom: 10px;
                transition: background-color 0.3s, transform 0.2s;
                width: 100%;
            }
            .select-deselect-companies-btn:hover {
                background-color: #B8860B; /* Ciemniejszy odcień żółci */
                transform: scale(1.05);
            }
            .select-deselect-companies-btn:active {
                transform: scale(0.95);
            }
            /* Styl dla przycisku "Zaznacz Wszystkie" w emailach */
            .select-deselect-emails-btn {
                background-color: #DAA520; /* Ciemnożółty kolor */
                color: #ffffff;
                padding: 5px 10px;
                border: none;
                border-radius: 5px;
                cursor: pointer;
                font-size: 14px;
                margin-bottom: 10px;
                transition: background-color 0.3s, transform 0.2s;
                width: 100%;
            }
            .select-deselect-emails-btn:hover {
                background-color: #B8860B; /* Ciemniejszy odcień żółci */
                transform: scale(1.05);
            }
            .select-deselect-emails-btn:active {
                transform: scale(0.95);
            }
            /* Individual segment's email list */
            .email-list {
                list-style: none;
                padding-left: 20px;
                margin-top: 10px;
                display: none;
                max-height: 300px;
                overflow-y: auto;
            }
            .email-list.show {
                display: block;
            }
            .email-item {
                display: flex;
                align-items: center;
                margin-bottom: 5px;
            }
            .email-item input[type="checkbox"] {
                margin-right: 10px;
                transform: scale(1.1);
            }
            .email-item label {
                flex: 1;
                cursor: pointer;
                color: #ffffff;
                display: flex;
                align-items: center;
                justify-content: space-between;
                font-size: 12px; /* Umiarkowany rozmiar czcionki */
            }
            /* Styl dla listy wybranych segmentów i możliwości */
            #selected-segments, #selected-possibilities {
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
                border: 1px solid #FFD700; /* Match panel color */
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
            /* Modal Styles */
            .modal {
                display: none; /* Hidden by default */
                position: fixed; /* Stay in place */
                z-index: 1002; /* Sit on top */
                left: 0;
                top: 0;
                width: 100%; /* Full width */
                height: 100%; /* Full height */
                overflow: auto; /* Enable scroll if needed */
                background-color: rgba(0,0,0,0.5); /* Black w/ opacity */
            }
            .modal-content {
                background-color: #fefefe;
                margin: 10% auto; /* 10% from the top and centered */
                padding: 20px;
                border: 1px solid #888;
                width: 80%; /* Could be more or less, depending on screen size */
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
            /* Dodatkowe style dla dropzone */
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
            /* Styl dla podglądu załączników */
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
            /* Progress Bar */
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
            /* Spinner Styles */
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
            /* Stopka */
            .footer {
                background-color: transparent;
                color: #aaaaaa;
                text-align: center;
                padding: 10px;
                font-size: 12px;
                margin-top: auto;
            }
            /* Responsive Design */
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
                #selected-segments, #selected-possibilities {
                    position: static;
                    margin-top: 10px;
                }
            }
        </style>
        <!-- Dodanie CKEditor CDN -->
        <script src="https://cdn.ckeditor.com/ckeditor5/39.0.1/classic/ckeditor.js"></script>
        <script>
            // Funkcje wspólne
            function showFlashMessage(category, message) {
                const flashMessage = document.querySelector(`.flash-message.${category}`);
                if (flashMessage) {
                    flashMessage.textContent = message;
                    flashMessage.classList.add('show');

                    // Automatyczne ukrywanie po 5 sekundach
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

            // Funkcja do aktualizacji listy notatek w interfejsie użytkownika
            function updateNotesList(notes) {
                const notesList = document.querySelector('.note-section ul');
                notesList.innerHTML = ''; // Wyczyść istniejącą listę notatek

                notes.forEach(note => {
                    const li = document.createElement('li');
                    li.className = 'note';
                    li.setAttribute('data-note-id', note.id);
                    li.innerHTML = `
                        <span>${escapeHtml(note.content)}</span>
                        <div class="note-actions">
                            <button type="button" class="transfer-note-btn" data-note-content="${escapeHtml(note.content)}">Transfer</button>
                            <button type="button" class="edit-btn" data-note-id="${note.id}" data-note-content="${escapeHtml(note.content)}">Edytuj</button>
                            <form class="delete-note-form" data-note-id="${note.id}">
                                <button type="submit" class="delete-btn">Usuń</button>
                                <div class="spinner" id="note-spinner-${note.id}" style="display: none;"></div>
                            </form>
                        </div>
                    `;
                    notesList.appendChild(li);
                });
            }

            // Escape HTML to prevent XSS in data attributes
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

            // Funkcja do przenoszenia treści notatki do pola "Wiadomość"
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

            // Funkcja do aktualizacji listy wybranych segmentów i możliwości
            function updateSelectedItems() {
                // Aktualizacja segmentów
                const selectedSegments = Array.from(document.querySelectorAll('.segment-item input[type="checkbox"]:checked'))
                    .map(cb => cb.value);
                const selectedSegmentsDiv = document.getElementById('selected-segments');
                selectedSegmentsDiv.innerHTML = ''; // Wyczyść istniejącą zawartość

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
                        // Odznacz checkbox w sidebarze
                        const checkbox = Array.from(document.querySelectorAll('.segment-item input[type="checkbox"]'))
                            .find(cb => cb.value === itemToRemove);
                        if (checkbox) {
                            checkbox.checked = false;
                            // Odznacz wszystkie e-maile w tym segmencie
                            const segmentIndex = checkbox.id.split('-')[1];
                            const emailList = document.getElementById(`emails-${segmentIndex}`);
                            if (emailList) {
                                const emailCheckboxes = emailList.querySelectorAll('input[type="checkbox"]');
                                emailCheckboxes.forEach(emailCb => {
                                    emailCb.checked = false;
                                });
                            }
                        }
                        // Usuń segment z wyświetlania
                        this.parentElement.remove();
                        // Aktualizacja listy wybranych segmentów i możliwości
                        updateSelectedItems();
                        updateSelectAllButtons();
                    });

                    segmentSpan.appendChild(removeSpan);
                    selectedSegmentsDiv.appendChild(segmentSpan);
                });

                // Aktualizacja możliwości
                const selectedPossibilities = Array.from(document.querySelectorAll('.possibility-item input[type="checkbox"]:checked'))
                    .map(cb => cb.value);
                const selectedPossibilitiesDiv = document.getElementById('selected-possibilities');
                selectedPossibilitiesDiv.innerHTML = ''; // Wyczyść istniejącą zawartość

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
                        // Odznacz checkbox w sidebarze
                        const checkbox = Array.from(document.querySelectorAll('.possibility-item input[type="checkbox"]'))
                            .find(cb => cb.value === itemToRemove);
                        if (checkbox) {
                            checkbox.checked = false;
                            // Odznacz wszystkie firmy w tej możliwości
                            const possibilityIndex = checkbox.id.split('-')[1];
                            const companyList = document.getElementById(`companies-${possibilityIndex}`);
                            if (companyList) {
                                const companyCheckboxes = companyList.querySelectorAll('input[type="checkbox"]');
                                companyCheckboxes.forEach(companyCb => {
                                    companyCb.checked = false;
                                });
                            }
                        }
                        // Usuń możliwość z wyświetlania
                        this.parentElement.remove();
                        // Aktualizacja listy wybranych segmentów i możliwości
                        updateSelectedItems();
                        updateSelectAllButtons();
                    });

                    possibilitySpan.appendChild(removeSpan);
                    selectedPossibilitiesDiv.appendChild(possibilitySpan);
                });

                // Aktualizacja tekstu przycisków "Zaznacz/Odznacz Wszystkie"
                updateSelectAllButtons();
            }

            // Drag and Drop for File Attachments
            document.addEventListener('DOMContentLoaded', function() {
                var dropzone = document.getElementById('dropzone');
                var fileInput = document.getElementById('attachments');
                var attachmentsPreview = document.getElementById('attachments-preview');
                var attachmentsCount = document.getElementById('attachments-count');
                var allFiles = []; // Array to hold all selected files

                // Event listeners for drag and drop
                dropzone.addEventListener('dragover', function(e) {
                    e.preventDefault();
                    dropzone.classList.add('dragover');
                });

                dropzone.addEventListener('dragleave', function(e) {
                    e.preventDefault();
                    dropzone.classList.remove('dragover');
                });

                dropzone.addEventListener('drop', function(e) {
                    e.preventDefault();
                    dropzone.classList.remove('dragover');
                    if (e.dataTransfer.files.length) {
                        appendFiles(e.dataTransfer.files);
                    }
                });

                dropzone.addEventListener('click', function() {
                    fileInput.click();
                });

                // Event listener for file input change
                fileInput.addEventListener('change', function() {
                    appendFiles(fileInput.files);
                });

                function isFileInList(file, fileList) {
                    for (var i = 0; i < fileList.length; i++) {
                        if (file.name === fileList[i].name && file.size === fileList[i].size && file.type === fileList[i].type) {
                            return true;
                        }
                    }
                    return false;
                }

                function appendFiles(files) {
                    for (var i = 0; i < files.length; i++) {
                        var file = files[i];
                        if (!isFileInList(file, allFiles)) {
                            if (allFiles.length < {{ max_attachments }}) {
                                allFiles.push(file);
                            } else {
                                showFlashMessage('error', "Możesz przesłać maksymalnie {{ max_attachments }} załączników.");
                                break;
                            }
                        } else {
                            showFlashMessage('warning', "Plik " + file.name + " już został dodany.");
                        }
                    }

                    // Update the file input
                    var dataTransfer = new DataTransfer();
                    for (var i = 0; i < allFiles.length; i++) {
                        dataTransfer.items.add(allFiles[i]);
                    }
                    fileInput.files = dataTransfer.files;

                    // Update the attachments preview and count
                    updateAttachmentsPreview();
                    updateAttachmentsCount(allFiles.length);
                }

                function updateAttachmentsPreview() {
                    attachmentsPreview.innerHTML = ''; // Clear existing previews
                    for (var i = 0; i < allFiles.length; i++) {
                        var file = allFiles[i];
                        var fileName = file.name;
                        if (fileName.length > 15) {
                            fileName = fileName.substring(0, 12) + '...';
                        }

                        var attachmentItem = document.createElement('div');
                        attachmentItem.classList.add('attachment-item');

                        var fileIcon = document.createElement('span');
                        fileIcon.textContent = '📎'; // Paperclip icon
                        attachmentItem.appendChild(fileIcon);

                        var fileNameSpan = document.createElement('span');
                        fileNameSpan.textContent = fileName;
                        attachmentItem.appendChild(fileNameSpan);

                        var removeButton = document.createElement('button');
                        removeButton.type = 'button';
                        removeButton.innerHTML = '&times;'; // '×' symbol
                        removeButton.dataset.index = i;
                        removeButton.addEventListener('click', function() {
                            removeFile(this.dataset.index);
                        });
                        attachmentItem.appendChild(removeButton);

                        attachmentsPreview.appendChild(attachmentItem);
                    }
                }

                function removeFile(index) {
                    allFiles.splice(index, 1);

                    // Update the file input
                    var dataTransfer = new DataTransfer();
                    for (var i = 0; i < allFiles.length; i++) {
                        dataTransfer.items.add(allFiles[i]);
                    }
                    fileInput.files = dataTransfer.files;

                    updateAttachmentsPreview();
                    updateAttachmentsCount(allFiles.length);
                }

                function updateAttachmentsCount(count) {
                    attachmentsCount.textContent = "Załączników: " + count + "/{{ max_attachments }}";
                }

                // Initialize attachments count
                updateAttachmentsCount(0);
            });

            // Inicjalizacja CKEditor z synchronizacją danych i walidacją
            document.addEventListener('DOMContentLoaded', function() {
                ClassicEditor
                    .create(document.querySelector('#message-editor'), {
                        toolbar: ['bold', 'italic', 'underline', 'bulletedList', 'numberedList', 'link']
                    })
                    .then(editor => {
                        window.editor = editor;
                        console.log('CKEditor został zainicjalizowany.');

                        // Synchronizacja danych CKEditor z textarea przed wysłaniem formularza
                        const form = document.getElementById('main-form');
                        form.addEventListener('submit', (event) => {
                            event.preventDefault(); // Zapobiegaj tradycyjnemu przesłaniu formularza

                            const data = editor.getData();
                            document.querySelector('#message').value = data;

                            // Walidacja, czy pole message nie jest puste
                            const tempElement = document.createElement('div');
                            tempElement.innerHTML = data;
                            const textContent = tempElement.textContent || tempElement.innerText || '';
                            if (textContent.trim() === '') {
                                showFlashMessage('error', 'Pole "Wiadomość" nie może być puste.');
                                // Ustaw fokus na edytor CKEditor
                                editor.editing.view.focus();
                                return;
                            }

                            // Pokazanie spinnera
                            showSpinner('spinner');

                            // Pobranie danych formularza
                            const formData = new FormData(form);

                            // Wysyłanie danych przez AJAX do send_message_ajax
                            fetch('{{ url_for("send_message_ajax") }}', {
                                method: 'POST',
                                body: formData,
                                credentials: 'same-origin' // Umożliwia przesyłanie ciasteczek sesji
                            })
                            .then(response => response.json())
                            .then(data => {
                                // Ukrycie spinnera
                                hideSpinner('spinner');

                                if (data.success) {
                                    showFlashMessage('success', data.message);
                                    // Opcjonalnie: Zresetowanie formularza po sukcesie
                                    form.reset();
                                    document.getElementById('attachments-preview').innerHTML = '';
                                    document.getElementById('attachments-count').textContent = `Załączników: 0/{{ max_attachments }}`;
                                    editor.setData('');
                                    // Aktualizacja wyświetlanych segmentów i możliwości
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
            });

            // Funkcje Toggle Segments i Possibilities
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

            // Toggle Select All Checkboxes for Segments
            function toggleSelectAllSegments(button) {
                var segmentCheckboxes = document.querySelectorAll('.segment-item input[type="checkbox"]');
                var allChecked = Array.from(segmentCheckboxes).every(cb => cb.checked);

                segmentCheckboxes.forEach(function(checkbox) {
                    checkbox.checked = !allChecked;
                    handleSegmentChange(checkbox);
                });

                // Aktualizacja tekstu przycisku
                button.textContent = !allChecked ? 'Odznacz wszystkie segmenty' : 'Zaznacz wszystkie segmenty';

                // Aktualizacja listy wybranych segmentów i możliwości
                updateSelectedItems();
            }

            // Toggle Select All Checkboxes for Possibilities
            function toggleSelectAllPossibilities(button) {
                var possibilityCheckboxes = document.querySelectorAll('.possibility-item input[type="checkbox"]');
                var allChecked = Array.from(possibilityCheckboxes).every(cb => cb.checked);

                possibilityCheckboxes.forEach(function(checkbox) {
                    checkbox.checked = !allChecked;
                    handlePossibilityChange(checkbox);
                });

                // Aktualizacja tekstu przycisku
                button.textContent = !allChecked ? 'Odznacz wszystkie możliwości' : 'Zaznacz wszystkie możliwości';

                // Aktualizacja listy wybranych segmentów i możliwości
                updateSelectedItems();
            }

            // Toggle Select All Emails in a Segment
            function toggleSelectAllEmailsInSegment(emailListId) {
                var emailList = document.getElementById(emailListId);
                var emailCheckboxes = emailList.querySelectorAll('input[type="checkbox"]');
                var toggleBtn = emailList.querySelector('.select-deselect-emails-btn');

                var allChecked = Array.from(emailCheckboxes).every(cb => cb.checked);

                emailCheckboxes.forEach(function(checkbox) {
                    checkbox.checked = !allChecked;
                });

                // Aktualizuj przycisk
                toggleBtn.textContent = !allChecked ? 'Odznacz Wszystkie' : 'Zaznacz Wszystkie';

                // Zmień kolor przycisku
                toggleBtn.style.backgroundColor = '#DAA520'; // Ciemnożółty kolor

                // Aktualizacja listy wybranych segmentów i możliwości
                updateSelectedItems();
            }

            // Toggle Select All Companies in a Possibility
            function toggleSelectAllCompaniesInPossibility(companyListId) {
                var companyList = document.getElementById(companyListId);
                var companyCheckboxes = companyList.querySelectorAll('input[type="checkbox"]');
                var toggleBtn = companyList.querySelector('.select-deselect-companies-btn');

                var allChecked = Array.from(companyCheckboxes).every(cb => cb.checked);

                companyCheckboxes.forEach(function(checkbox) {
                    checkbox.checked = !allChecked;
                });

                // Aktualizuj przycisk
                toggleBtn.textContent = !allChecked ? 'Odznacz Wszystkie' : 'Zaznacz Wszystkie';

                // Zmień kolor przycisku
                toggleBtn.style.backgroundColor = '#DAA520'; // Ciemnożółty kolor

                // Aktualizacja listy wybranych segmentów i możliwości
                updateSelectedItems();
            }

            // Toggle All Segments (Expand/Collapse)
            function toggleAllSegmentsExpandCollapse(button) {
                var emailLists = document.querySelectorAll('.email-list');
                var allExpanded = Array.from(emailLists).every(el => el.classList.contains('show'));

                emailLists.forEach(function(emailList) {
                    if (allExpanded) {
                        emailList.classList.remove('show');
                    } else {
                        emailList.classList.add('show');
                    }
                });

                // Aktualizuj przycisk
                button.textContent = allExpanded ? 'Rozwiń wszystkie segmenty' : 'Zwiń wszystkie segmenty';

                // Zmień kolor przycisku
                button.style.backgroundColor = '#DAA520'; // Ciemnożółty kolor
            }

            // Toggle All Possibilities (Expand/Collapse)
            function toggleAllPossibilitiesExpandCollapse(button) {
                var companyLists = document.querySelectorAll('.company-list');
                var allExpanded = Array.from(companyLists).every(el => el.classList.contains('show'));

                companyLists.forEach(function(companyList) {
                    if (allExpanded) {
                        companyList.classList.remove('show');
                    } else {
                        companyList.classList.add('show');
                    }
                });

                // Aktualizuj przycisk
                button.textContent = allExpanded ? 'Rozwiń wszystkie możliwości' : 'Zwiń wszystkie możliwości';

                // Zmień kolor przycisku
                button.style.backgroundColor = '#DAA520'; // Ciemnożółty kolor
            }

            // Funkcja do zaznaczania/odznaczania emaili w segmencie
            function toggleEmailsInSegment(segmentCheckbox) {
                var segmentIndex = segmentCheckbox.id.split('-')[1];
                var emailList = document.getElementById('emails-' + segmentIndex);
                if (emailList) {
                    var emailCheckboxes = emailList.querySelectorAll('input[type="checkbox"]');
                    emailCheckboxes.forEach(function(emailCheckbox) {
                        emailCheckbox.checked = segmentCheckbox.checked;
                    });
                }
            }

            // Funkcja do zaznaczania/odznaczania firm w możliwości
            function toggleCompaniesInPossibility(possibilityCheckbox) {
                var possibilityIndex = possibilityCheckbox.id.split('-')[1];
                var companyList = document.getElementById('companies-' + possibilityIndex);
                if (companyList) {
                    var companyCheckboxes = companyList.querySelectorAll('input[type="checkbox"]');
                    companyCheckboxes.forEach(function(companyCheckbox) {
                        companyCheckbox.checked = possibilityCheckbox.checked;
                    });
                }
            }

            // Funkcje handleSegmentChange i handlePossibilityChange
            function handleSegmentChange(segmentCheckbox) {
                toggleEmailsInSegment(segmentCheckbox);
                updateSelectedItems();
            }

            function handlePossibilityChange(possibilityCheckbox) {
                toggleCompaniesInPossibility(possibilityCheckbox);
                updateSelectedItems();
            }

            // Funkcja toggleEmailList
            function toggleEmailList(segmentIndex) {
                var emailList = document.getElementById('emails-' + segmentIndex);
                if (emailList) {
                    emailList.classList.toggle('show');
                }
            }

            // Funkcja toggleCompanyList
            function toggleCompanyList(possibilityIndex) {
                var companyList = document.getElementById('companies-' + possibilityIndex);
                if (companyList) {
                    companyList.classList.toggle('show');
                }
            }

            // Funkcja do aktualizacji przycisków "Zaznacz/Odznacz Wszystkie" po zmianie stanu checkboxów
            function updateSelectAllButtonsOnChange() {
                updateSelectAllButtons();
                updateEmailToggleButtons();
                updateCompanyToggleButtons();
            }

            // Funkcja do aktualizacji przycisków "Zaznacz/Odznacz Wszystkie"
            function updateSelectAllButtons() {
                var selectAllSegmentsButton = document.getElementById('select-all-segments-btn');
                var segmentCheckboxes = document.querySelectorAll('.segment-item input[type="checkbox"]');
                var allSegmentsChecked = Array.from(segmentCheckboxes).every(cb => cb.checked);
                selectAllSegmentsButton.textContent = allSegmentsChecked ? 'Odznacz wszystkie segmenty' : 'Zaznacz wszystkie segmenty';
                selectAllSegmentsButton.style.backgroundColor = '#DAA520'; // Ciemnożółty kolor

                var selectAllPossibilitiesButton = document.getElementById('select-all-possibilities-btn');
                var possibilityCheckboxes = document.querySelectorAll('.possibility-item input[type="checkbox"]');
                var allPossibilitiesChecked = Array.from(possibilityCheckboxes).every(cb => cb.checked);
                selectAllPossibilitiesButton.textContent = allPossibilitiesChecked ? 'Odznacz wszystkie możliwości' : 'Zaznacz wszystkie możliwości';
                selectAllPossibilitiesButton.style.backgroundColor = '#DAA520'; // Ciemnożółty kolor
            }

            // Funkcja do aktualizacji przycisków toggle dla emaili
            function updateEmailToggleButtons() {
                var emailLists = document.querySelectorAll('.email-list');
                emailLists.forEach(function(emailList) {
                    var emailCheckboxes = emailList.querySelectorAll('input[type="checkbox"]');
                    var toggleBtn = emailList.querySelector('.select-deselect-emails-btn');

                    var allChecked = Array.from(emailCheckboxes).every(cb => cb.checked);

                    toggleBtn.textContent = allChecked ? 'Odznacz Wszystkie' : 'Zaznacz Wszystkie';
                    toggleBtn.style.backgroundColor = '#DAA520'; // Ciemnożółty kolor
                });
            }

            // Funkcja do aktualizacji przycisków toggle dla firm
            function updateCompanyToggleButtons() {
                var companyLists = document.querySelectorAll('.company-list');
                companyLists.forEach(function(companyList) {
                    var companyCheckboxes = companyList.querySelectorAll('input[type="checkbox"]');
                    var toggleBtn = companyList.querySelector('.select-deselect-companies-btn');

                    var allChecked = Array.from(companyCheckboxes).every(cb => cb.checked);

                    toggleBtn.textContent = allChecked ? 'Odznacz Wszystkie' : 'Zaznacz Wszystkie';
                    toggleBtn.style.backgroundColor = '#DAA520'; // Ciemnożółty kolor
                });
            }

            // Delegacja zdarzeń dla usuwania pojedynczych notatek
            document.addEventListener('submit', function(event) {
                if (event.target && event.target.classList.contains('delete-note-form')) {
                    event.preventDefault();
                    const noteId = event.target.getAttribute('data-note-id');
                    const spinnerId = `note-spinner-${noteId}`;

                    // Wyświetlenie spinnera
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
                        // Ukrycie spinnera
                        hideSpinner(spinnerId);

                        if (data.success) {
                            showFlashMessage('success', data.message);
                            // Aktualizacja listy notatek
                            updateNotesList(data.notes);
                        } else {
                            showFlashMessage('error', data.message);
                        }
                    })
                    .catch(error => {
                        console.error('Błąd:', error);
                        hideSpinner(spinnerId);
                        showFlashMessage('error', 'Wystąpił błąd podczas usuwania notatki.');
                    });
                }
            });

            // Delegacja zdarzeń dla usuwania wszystkich notatek
            document.addEventListener('submit', function(event) {
                if (event.target && event.target.id === 'delete-all-notes-form') {
                    event.preventDefault();
                    const spinnerId = 'delete-all-spinner';

                    // Wyświetlenie spinnera
                    showSpinner(spinnerId);

                    fetch('{{ url_for("delete_all_notes_ajax") }}', {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json',
                        },
                        body: JSON.stringify({}), // Nie potrzeba danych
                        credentials: 'same-origin'
                    })
                    .then(response => response.json())
                    .then(data => {
                        // Ukrycie spinnera
                        hideSpinner(spinnerId);

                        if (data.success) {
                            showFlashMessage('success', data.message);
                            // Aktualizacja listy notatek
                            updateNotesList(data.notes);
                        } else {
                            showFlashMessage('error', data.message);
                        }
                    })
                    .catch(error => {
                        console.error('Błąd:', error);
                        hideSpinner(spinnerId);
                        showFlashMessage('error', 'Wystąpił błąd podczas usuwania notatek.');
                    });
                }
            });

            // Delegacja zdarzeń dla dodawania notatki
            document.addEventListener('submit', function(event) {
                if (event.target && event.target.id === 'add-note-form') {
                    event.preventDefault();
                    const form = event.target;
                    const noteInput = form.querySelector('input[name="note"]');
                    const noteContent = noteInput.value.trim();
                    const spinnerId = 'note-spinner';

                    if (noteContent === '') {
                        showFlashMessage('error', 'Nie można dodać pustej notatki.');
                        return;
                    }

                    // Wyświetlenie spinnera
                    showSpinner(spinnerId);

                    fetch('{{ url_for("add_note_ajax") }}', {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json',
                        },
                        body: JSON.stringify({ note: noteContent }),
                        credentials: 'same-origin'
                    })
                    .then(response => response.json())
                    .then(data => {
                        // Ukrycie spinnera
                        hideSpinner(spinnerId);

                        if (data.success) {
                            showFlashMessage('success', data.message);
                            // Aktualizacja listy notatek
                            updateNotesList(data.notes);
                            // Wyczyść pole notatki
                            noteInput.value = '';
                        } else {
                            showFlashMessage('error', data.message);
                        }
                    })
                    .catch(error => {
                        console.error('Błąd:', error);
                        hideSpinner(spinnerId);
                        showFlashMessage('error', 'Wystąpił błąd podczas dodawania notatki.');
                    });
                }
            });

            // Funkcja do otwierania modalnego okna edycji notatki
            function openEditModal(noteId, currentContent) {
                const modal = document.getElementById('editModal');
                const editForm = document.getElementById('edit-note-form');
                const editInput = document.getElementById('edit-note-input');
                const closeModalBtn = document.getElementById('closeEditModal');

                // Ustawienie obecnej treści notatki w polu edycji
                editInput.value = currentContent;
                // Przechowywanie ID notatki w formularzu
                editForm.setAttribute('data-note-id', noteId);

                // Wyświetlenie modalnego okna
                modal.style.display = 'block';

                // Obsługa zamykania modala po kliknięciu na przycisk zamknięcia
                closeModalBtn.onclick = function() {
                    closeEditModal();
                }

                // Zamknięcie modalnego okna po kliknięciu poza treścią modala
                window.onclick = function(event) {
                    if (event.target == modal) {
                        closeEditModal();
                    }
                }
            }

            // Zamknięcie modalnego okna
            function closeEditModal() {
                const modal = document.getElementById('editModal');
                modal.style.display = 'none';
            }

            // Funkcja do edycji notatki
            function editNote(noteId, newContent) {
                // Pokazanie spinnera
                showSpinner(`edit-spinner-${noteId}`);

                // Wysłanie żądania AJAX do edycji notatki
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
                    // Ukrycie spinnera
                    hideSpinner(`edit-spinner-${noteId}`);

                    if (data.success) {
                        showFlashMessage('success', data.message);
                        // Aktualizacja treści notatki w interfejsie użytkownika
                        const noteSpan = document.querySelector(`.note[data-note-id="${noteId}"] span`);
                        if (noteSpan) {
                            noteSpan.textContent = data.note.content;
                        }
                        // Aktualizacja atrybutów data-note-content
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

                    // Zamknięcie modalnego okna
                    closeEditModal();
                })
                .catch(error => {
                    console.error('Błąd:', error);
                    hideSpinner(`edit-spinner-${noteId}`);
                    showFlashMessage('error', 'Wystąpił błąd podczas edycji notatki.');
                });
            }

            // Delegacja zdarzeń dla przycisków "Edytuj"
            document.addEventListener('click', function(event) {
                if (event.target && event.target.classList.contains('edit-btn')) {
                    const noteId = event.target.getAttribute('data-note-id');
                    const noteContent = event.target.getAttribute('data-note-content');
                    console.log('Kliknięto przycisk Edytuj dla notatki:', noteId);
                    openEditModal(noteId, noteContent);
                }
            });

            // Delegacja zdarzeń dla formularza edycji notatki
            document.addEventListener('submit', function(event) {
                if (event.target && event.target.id === 'edit-note-form') {
                    event.preventDefault();
                    const form = event.target;
                    const noteId = form.getAttribute('data-note-id');
                    const newContent = document.getElementById('edit-note-input').value.trim();
                    const spinnerId = `edit-spinner-${noteId}`;

                    if (newContent === '') {
                        showFlashMessage('error', 'Nowa treść notatki nie może być pusta.');
                        return;
                    }

                    // Wywołanie funkcji edytującej notatkę
                    editNote(noteId, newContent);
                }
            });

            // Funkcja do obsługi transferowania notatek
            document.addEventListener('click', function(event) {
                if (event.target && event.target.classList.contains('transfer-note-btn')) {
                    const noteContent = event.target.getAttribute('data-note-content');
                    console.log('Kliknięto przycisk Transfer. Treść notatki:', noteContent);
                    transferToMessageField(noteContent);
                    showFlashMessage('success', 'Treść notatki została przeniesiona do pola "Wiadomość".');
                }
            });

            // Aktualizacja wyświetlanych segmentów i możliwości przy załadowaniu strony
            document.addEventListener('DOMContentLoaded', function() {
                updateSelectedItems();
                updateSelectAllButtons();
                updateEmailToggleButtons();
                updateCompanyToggleButtons();
            });

            // Dodanie funkcji toggle dla panelu bocznego
            document.addEventListener('DOMContentLoaded', function() {
                const sidebarToggleBtn = document.getElementById('sidebar-toggle');
                const sidebar = document.querySelector('.sidebar');
                const mainContent = document.querySelector('.main-content');

                sidebarToggleBtn.addEventListener('click', function() {
                    sidebar.classList.toggle('active');
                    mainContent.classList.toggle('sidebar-active');
                });
            });
        </script>
    </head>
    <body>
        <!-- Nowy Header -->
        <header class="top-header">
            <div class="header-left">
                <!-- Przycisk toggle sidebar -->
                <button id="sidebar-toggle" class="sidebar-toggle-btn">&#9776;</button>
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
        
        <!-- Wrapper na zawartość z formularzem email -->
        <form id="main-form" class="main-form" enctype="multipart/form-data">
            <div class="content-wrapper">
                <!-- Sidebar dla zarządzania segmentami i możliwościami -->
                <div class="sidebar">
                    <!-- Container for toggle buttons placed side by side -->
                    <div class="toggle-buttons-container">
                        <!-- Przycisk do toggle segmentów -->
                        <button type="button" class="toggle-segments-btn" onclick="toggleSegmentsList(this)">
                            <img src="{{ url_for('static', filename='hammer.png') }}" alt="Toggle Segments">
                        </button>

                        <!-- Przycisk do toggle możliwości transportowych zastąpiony obrazkiem greek_key.png -->
                        <button type="button" class="toggle-possibilities-btn" onclick="togglePossibilitiesList(this)">
                            <img src="{{ url_for('static', filename='greek_key.png') }}" alt="Toggle Possibilities">
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
                                    <label class="segment-label" onclick="toggleEmailList({{ segment_index }})">
                                        {{ segment }} <span class="segment-count">(Polski: {{ counts['Polski'] }}, Zagraniczny: {{ counts['Zagraniczny'] }})</span>
                                    </label>
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
                                    <label class="possibility-label" onclick="toggleCompanyList({{ possibility_index }})">
                                        {{ possibility }} <span class="company-count">({{ companies|length }})</span>
                                    </label>
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
                </div>

                <!-- Główna treść strony -->
                <div class="main-content">
                    <div class="form-container">
                        <h1>e-Communicator</h1>

                        <!-- Flash Messages -->
                        <div class="flash-message success"></div>
                        <div class="flash-message error"></div>
                        <div class="flash-message warning"></div>

                        <!-- Formularz wysyłania e-maili -->
                        <label for="subject">Temat:</label>
                        <input type="text" id="subject" name="subject" required>

                        <label for="message-editor">Wiadomość:</label>
                        <div id="message-editor"></div>
                        <textarea name="message" id="message" style="display: none;"></textarea>

                        <!-- Pole załączników -->
                        <label for="attachments">Załączniki:</label>
                        <input type="file" name="attachments" id="attachments" multiple style="display: none;">
                        <div id="dropzone" class="dropzone">
                            Przeciągnij i upuść pliki tutaj lub kliknij, aby wybrać.
                        </div>
                        <!-- Sekcja do wyświetlania podglądu załączników -->
                        <div id="attachments-preview" class="attachments-preview"></div>
                        <!-- Licznik załączników -->
                        <div id="attachments-count" class="attachments-count">Załączników: 0/{{ max_attachments }}</div>

                        <label for="language">Wybierz język:</label>
                        <select id="language" name="language" required>
                            <option value="" disabled selected>Wybierz język</option>
                            <option value="Polski">Polski</option>
                            <option value="Zagraniczny">Zagraniczny</option>
                        </select>

                        <!-- Przycisk "Wyślij" z spinnerem i progress bar -->
                        <div class="button-container" style="display: flex; align-items: flex-start; flex-wrap: wrap; margin-top: 20px;">
                            <button type="submit" id="send-button">Wyślij</button>
                            <div id="selected-segments" style="display: flex; gap: 5px; flex-wrap: wrap;"></div>
                            <div id="selected-possibilities" style="display: flex; gap: 5px; flex-wrap: wrap;"></div>
                            <div class="spinner" id="spinner" style="display: none;"></div>
                        </div>

                        <!-- Progress Bar -->
                        <div class="progress-container" style="display: none;">
                            <div class="progress-bar">0%</div>
                        </div>
                    </div>
                </div>
            </div>
        </form>

        <!-- Sekcja Notatek poza głównym formularzem -->
        <div class="note-section">
            <h3>Notatki</h3>
            <!-- Formularz dodawania notatki -->
            <form id="add-note-form">
                <input type="text" name="note" placeholder="Dodaj notatkę..." required>
                <button type="submit">Dodaj notatkę</button>
                <div class="spinner" id="note-spinner" style="display: none;"></div>
            </form>
            <ul>
                {% for note in notes %}
                    <li class="note" data-note-id="{{ note.id }}">
                        <span>{{ note.content }}</span>
                        <div class="note-actions">
                            <button type="button" class="transfer-note-btn" data-note-content="{{ note.content|e }}">Transfer</button>
                            <button type="button" class="edit-btn" data-note-id="{{ note.id }}" data-note-content="{{ note.content|e }}">Edytuj</button>
                            <form class="delete-note-form" data-note-id="{{ note.id }}">
                                <button type="submit" class="delete-btn">Usuń</button>
                                <div class="spinner" id="note-spinner-{{ note.id }}" style="display: none;"></div>
                            </form>
                        </div>
                    </li>
                {% endfor %}
            </ul>
            {% if notes %}
                <!-- Formularz usuwania wszystkich notatek -->
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
            ©DigitDrago
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