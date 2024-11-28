import os
from app import db, LicenseKey, app
from datetime import datetime, timedelta, timezone  # Dodano 'timezone'

# Zastąp '7d9c2498-fd9e-4ebb-82ce-7c0b46491d61' swoim rzeczywistym kluczem
license_key_value = '7d9c2498-fd9e-4ebb-82ce-7c0b46491d61'

# Ustaw datę wygaśnięcia klucza (np. za 100 dni)
expiration_date = datetime.now(timezone.utc) + timedelta(days=100)

with app.app_context():
    # Sprawdź, czy klucz już istnieje
    existing_key = LicenseKey.query.filter_by(key=license_key_value).first()
    if not existing_key:
        # Dodaj nowy klucz licencyjny
        new_license_key = LicenseKey(
            key=license_key_value,
            expiration_date=expiration_date,
            is_revoked=False
        )
        db.session.add(new_license_key)
        db.session.commit()
        print("Klucz licencyjny został dodany do bazy danych.")
    else:
        print("Klucz licencyjny już istnieje w bazie danych.")
