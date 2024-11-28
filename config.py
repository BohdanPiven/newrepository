import os

class Config:
    SMTP_SERVER = os.getenv('SMTP_SERVER', 'smtp.office365.com')
    SMTP_PORT = int(os.getenv('SMTP_PORT', 587))
    EMAIL_ADDRESS = os.getenv('EMAIL_ADDRESS', 'sm@dlglogistics.pl')
    EMAIL_PASSWORD = os.getenv('EMAIL_PASSWORD', 'Mz024%r6')
    SERVICE_ACCOUNT_FILE = os.getenv('SERVICE_ACCOUNT_FILE', 'credentials.json')
    SPREADSHEET_ID = os.getenv('SPREADSHEET_ID', '1O4QpLXpjLkmMwa8SuRfNzjO3Yc6PqE3JtU5IppYmlVI')
    RANGE_NAME = os.getenv('RANGE_NAME', 'data!A1:AA3000')
