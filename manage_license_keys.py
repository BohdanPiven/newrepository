# manage_license_keys.py

import argparse
from app import db, LicenseKey, app  # Importuj obiekt aplikacji
from datetime import datetime, timedelta, timezone

def create_license_key(key_value, days_valid=30):
    expiration_date = datetime.now(timezone.utc) + timedelta(days=days_valid)
    with app.app_context():  # Uruchom kontekst aplikacji
        # Sprawdź, czy klucz już istnieje
        existing_key = LicenseKey.query.filter_by(key=key_value).first()
        if not existing_key:
            # Dodaj nowy klucz licencyjny
            new_license_key = LicenseKey(
                key=key_value,
                expiration_date=expiration_date,
                is_revoked=False
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
    with app.app_context():  # Uruchom kontekst aplikacji
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
            print(f"Klucz: {key.key}, Wygasa: {expiration}, Status: {status}")

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Zarządzanie kluczami licencyjnymi.")
    subparsers = parser.add_subparsers(dest='command', help='Dostępne komendy')

    # Komenda create
    parser_create = subparsers.add_parser('create', help='Tworzy nowy klucz licencyjny')
    parser_create.add_argument('--key', required=True, help='Unikalny klucz licencyjny')
    parser_create.add_argument('--days', type=int, default=30, help='Liczba dni ważności klucza (domyślnie 30)')

    # Komenda revoke
    parser_revoke = subparsers.add_parser('revoke', help='Unieważnia istniejący klucz licencyjny')
    parser_revoke.add_argument('--key', required=True, help='Klucz licencyjny do unieważnienia')

    # Komenda list
    parser_list = subparsers.add_parser('list', help='Wyświetla wszystkie klucze licencyjne')

    args = parser.parse_args()

    if args.command == 'create':
        create_license_key(args.key, days_valid=args.days)
    elif args.command == 'revoke':
        revoke_license_key(args.key)
    elif args.command == 'list':
        list_license_keys()
    else:
        parser.print_help()
