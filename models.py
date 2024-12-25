# models.py
from flask_sqlalchemy import SQLAlchemy
import sqlalchemy as sa
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()

PASTEL_COLORS = [
    "#e0f7fa",  # Pastelowy błękit
    "#f8bbd0",  # Pastelowy róż
    "#d1c4e9",  # Pastelowy fiolet
    "#c8e6c9",  # Pastelowa zieleń
    "#fff9c4",  # Pastelowy żółty
    "#ffe0b2",  # Pastelowy pomarańcz
    "#d7ccc8",  # Pastelowy brąz
    "#c5cae9",  # Pastelowy niebieski
    "#ffccbc",  # Pastelowy koral
    "#d1adfc",  # Pastelowy liliowy
    # Dodaj więcej kolorów według potrzeb
]

class LicenseKey(db.Model):
    __tablename__ = 'license_key'
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(100), nullable=False, unique=True)
    expiration_date = db.Column(db.DateTime, nullable=False)
    is_revoked = db.Column(db.Boolean, nullable=True)
    revoked_reason = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, nullable=True)
    updated_at = db.Column(db.DateTime, nullable=True)

    user = db.relationship('User', back_populates='license_key', uselist=False)

class User(db.Model):
    __tablename__ = 'user'
    __table_args__ = (
        sa.UniqueConstraint('username', name='uq_user_username'),
        sa.UniqueConstraint('email_address', name='uq_user_email_address'),
        sa.UniqueConstraint('reset_code', name='uq_user_reset_code'),
        sa.UniqueConstraint('license_key_id', name='uq_user_license_key_id'),
    )

    id = db.Column(db.Integer, primary_key=True)
    first_name = db.Column(db.String(150), nullable=False)
    last_name = db.Column(db.String(150), nullable=False)
    position = db.Column(db.String(150), nullable=False)
    username = db.Column(db.String(150), nullable=False)
    email_address = db.Column(db.String(150), nullable=False)
    email_password = db.Column(db.String(500), nullable=False)
    app_password_hash = db.Column(db.String(128), nullable=False)
    phone_number = db.Column(db.String(20), nullable=False)
    license_key_id = db.Column(db.Integer, db.ForeignKey('license_key.id'), nullable=False)
    reset_code = db.Column(db.String(6), nullable=True)
    reset_code_expiration = db.Column(db.DateTime, nullable=True)
    # Najpierw pozwalamy na NULL i ustawiamy domyślną wartość serwerową
    color = db.Column(db.String(7), nullable=True, server_default="'#e0f7fa'")


    license_key = db.relationship('LicenseKey', back_populates='user', cascade='all, delete')

    verification_codes = db.relationship(
        'VerificationCode',
        backref='user',
        cascade='all, delete, delete-orphan',
        lazy=True
    )

    notes = db.relationship(
        'Note',
        backref='user',
        cascade='all, delete, delete-orphan',
        lazy=True
    )

    def set_app_password(self, password):
        self.app_password_hash = generate_password_hash(password)

    def check_app_password(self, password):
        return check_password_hash(self.app_password_hash, password)

class Note(db.Model):
    __tablename__ = 'note'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    content = db.Column(db.String(500), nullable=False)

class VerificationCode(db.Model):
    __tablename__ = 'verification_code'
    __table_args__ = (
        sa.UniqueConstraint('code', name='uq_verification_code_code'),
    )

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    code = db.Column(db.String(6), nullable=False)
    expiration_time = db.Column(db.DateTime, nullable=False)
