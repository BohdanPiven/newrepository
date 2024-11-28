# models.py
from flask_sqlalchemy import SQLAlchemy
import sqlalchemy as sa
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()

class LicenseKey(db.Model):
    __tablename__ = 'license_key'
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(100), nullable=False, unique=True)
    expiration_date = db.Column(db.DateTime, nullable=False)
    is_revoked = db.Column(db.Boolean, nullable=True)
    revoked_reason = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, nullable=True)
    updated_at = db.Column(db.DateTime, nullable=True)

    # Relacja z użytkownikami (One-to-Many)
    users = db.relationship('User', backref='license_key', lazy=True)

class User(db.Model):
    __tablename__ = 'user'
    __table_args__ = (
        sa.UniqueConstraint('username', name='uq_user_username'),
        sa.UniqueConstraint('email_address', name='uq_user_email_address'),
        sa.UniqueConstraint('reset_code', name='uq_user_reset_code'),
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

    # Relacja z VerificationCode (One-to-Many) z kaskadowym usuwaniem
    verification_codes = db.relationship(
        'VerificationCode',
        backref='user',
        cascade='all, delete, delete-orphan',
        lazy=True
    )

    # Relacja z Note (One-to-Many) z kaskadowym usuwaniem
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
