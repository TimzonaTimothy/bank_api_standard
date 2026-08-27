from datetime import timedelta
from os import path, getenv
from dotenv import load_dotenv
from .base import * # noga
from .base import BASE_DIR 

local_env_file = path.join(BASE_DIR, '.envs', '.env.local')
if path.isfile(local_env_file):
    load_dotenv(local_env_file)
    
SECRET_KEY = getenv('SECRET_KEY')

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = getenv('DEBUG')


SITE_NAME = getenv('SITE_NAME', 'localhost')

ALLOWED_HOSTS = ["localhost", "127.0.0.1", "0.0.0.0"]

ADMIN_URL = getenv('ADMIN_URL', 'admin/')

EMAIL_BACKEND = "djcelery_email.backends.CeleryEmailBackend"

EMAIL_HOST = getenv('EMAIL_HOST')
EMAIL_PORT = getenv('EMAIL_PORT')
DEFAULT_FROM_EMAIL = getenv('DEFAULT_FROM_EMAIL')
DOMAIN = getenv('DOMAIN')

MAX_UPLOAD_SIZE = 1 * 1024 * 1024  # 1 MB

CSRF_TRUSTED_ORIGINS = ["http://localhost:8080","http://127.0.0.1:8080"]

LOCKOUT_DURATION = timedelta(minutes=30)  # Duration of lockout period

LOGIN_ATTEMPTS = 5  # Number of allowed failed login attempts before lockout

OTP_EXPIRATION = timedelta(minutes=5)  # OTP expiration time