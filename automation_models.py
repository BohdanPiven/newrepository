from app import db  # Upewnij się, że importujesz instancję SQLAlchemy z głównego pliku aplikacji
from datetime import date, time

class ScheduledPost(db.Model):
    __tablename__ = 'scheduled_posts'
    
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.Date, nullable=False)
    time = db.Column(db.Time, nullable=False)
    topic = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    
    def __init__(self, date, time, topic, description, user_id):
        self.date = date
        self.time = time
        self.topic = topic
        self.description = description
        self.user_id = user_id

    def __repr__(self):
        return f"<ScheduledPost {self.topic} on {self.date} at {self.time}>"
