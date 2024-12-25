# manage_license_keys.py

import argparse
import uuid  # Dodany import UUID
from app import app, db
from models import LicenseKey, User  # Upewnij się, że importujesz User, jeśli jest potrzebny
from datetime import datetime, timedelta, timezone
from werkzeug.security import generate_password_hash

def create_license_key(key_value=None, days_valid=30):
    if not key_value:
        key_value = str(uuid.uuid4())  # Generowanie unikalnego klucza
    expiration_date = datetime.now(timezone.utc) + timedelta(days=days_valid)
    with app.app_context():
        existing_key = LicenseKey.query.filter_by(key=key_value).first()
        if not existing_key:
            new_license_key = LicenseKey(
                key=key_value,
                expiration_date=expiration_date,
                is_revoked=False,
                revoked_reason=None,
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc)
            )
            db.session.add(new_license_key)
            try:
                db.session.commit()
                print(f"Klucz licencyjny został dodany do bazy danych: {new_license_key.key}")
            except Exception as e:
                db.session.rollback()
                print(f"Błąd podczas dodawania klucza: {e}")
        else:
            print(f"Klucz licencyjny już istnieje w bazie danych: {existing_key.key}")

def revoke_license_key(key_value):
    with app.app_context():
        key_to_revoke = LicenseKey.query.filter_by(key=key_value).first()
        if key_to_revoke:
            if not key_to_revoke.is_revoked:
                key_to_revoke.is_revoked = True
                try:
                    db.session.commit()
                    print(f"Klucz {key_to_revoke.key} został unieważniony.")
                except Exception as e:
                    db.session.rollback()
                    print(f"Błąd podczas unieważniania klucza: {e}")
            else:
                print(f"Klucz {key_to_revoke.key} jest już unieważniony.")
        else:
            print(f"Klucz {key_value} nie został znaleziony.")

def list_license_keys():
    with app.app_context():
        keys = LicenseKey.query.all()
        if not keys:
            print("Brak kluczy licencyjnych w bazie danych.")
            return
        for key in keys:
            status = "Unieważniony" if key.is_revoked else "Aktywny"
            expiration = key.expiration_date.strftime('%Y-%m-%d %H:%M:%S')
            assigned = key.user.username if key.user else "Brak przypisanego użytkownika"
            print(f"Klucz: {key.key}, Wygasa: {expiration}, Status: {status}, Użytkownik: {assigned}")

def assign_license_key(username, license_key_value):
    with app.app_context():
        user = User.query.filter_by(username=username).first()
        if not user:
            print(f"Użytkownik '{username}' nie został znaleziony.")
            return

        license_key = LicenseKey.query.filter_by(key=license_key_value).first()
        if not license_key:
            print(f"Klucz licencyjny '{license_key_value}' nie został znaleziony.")
            return
        elif license_key.user:
            print(f"Klucz licencyjny '{license_key.key}' jest już przypisany do użytkownika '{license_key.user.username}'.")
            return

        user.license_key = license_key
        try:
            db.session.commit()
            print(f"Klucz licencyjny '{license_key.key}' został przypisany do użytkownika '{user.username}'.")
        except Exception as e:
            db.session.rollback()
            print(f"Błąd podczas przypisywania klucza: {e}")

def delete_user_by_email(email):
    with app.app_context():
        user = User.query.filter_by(email_address=email).first()
        if user:
            username = user.username
            db.session.delete(user)
            try:
                db.session.commit()
                print(f"Użytkownik {username} z adresem e-mail {email} został usunięty wraz z przypisanym kluczem licencyjnym.")
            except Exception as e:
                db.session.rollback()
                print(f"Błąd podczas usuwania użytkownika: {e}")
        else:
            print(f"Użytkownik z adresem e-mail {email} nie został znaleziony.")

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Zarządzanie kluczami licencyjnymi i użytkownikami.")
    subparsers = parser.add_subparsers(dest='command', help='Dostępne komendy')

    # Komenda create
    parser_create = subparsers.add_parser('create', help='Tworzy nowy klucz licencyjny')
    parser_create.add_argument('--key', required=False, help='Unikalny klucz licencyjny (opcjonalny)')
    parser_create.add_argument('--days', type=int, default=30, help='Liczba dni ważności klucza (domyślnie 30)')

    # Komenda revoke
    parser_revoke = subparsers.add_parser('revoke', help='Unieważnia istniejący klucz licencyjny')
    parser_revoke.add_argument('--key', required=True, help='Klucz licencyjny do unieważnienia')

    # Komenda list
    parser_list = subparsers.add_parser('list', help='Wyświetla wszystkie klucze licencyjne')

    # Komenda assign
    parser_assign = subparsers.add_parser('assign', help='Przypisuje klucz licencyjny do użytkownika')
    parser_assign.add_argument('--username', required=True, help='Nazwa użytkownika')
    parser_assign.add_argument('--key', required=True, help='Klucz licencyjny do przypisania')

    # Komenda delete_user
    parser_delete_user = subparsers.add_parser('delete_user', help='Usuwa użytkownika na podstawie adresu e-mail')
    parser_delete_user.add_argument('--email', required=True, help='Adres e-mail użytkownika do usunięcia')

    args = parser.parse_args()

    if args.command == 'create':
        create_license_key(args.key, days_valid=args.days)
    elif args.command == 'revoke':
        revoke_license_key(args.key)
    elif args.command == 'list':
        list_license_keys()
    elif args.command == 'assign':
        assign_license_key(args.username, args.key)
    elif args.command == 'delete_user':
        delete_user_by_email(args.email)
    else:
        parser.print_help()
