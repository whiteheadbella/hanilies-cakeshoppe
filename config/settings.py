import os
import sys
from pathlib import Path
from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def _config_flag(name, default=False):
    raw_value = os.environ.get(name, str(default))
    normalized = str(raw_value).strip().lower()
    if normalized in {'1', 'true', 't', 'yes', 'y', 'on', 'debug', 'local'}:
        return True
    if normalized in {'0', 'false', 'f', 'no', 'n', 'off', 'release', 'prod', 'production'}:
        return False
    return default


def _config_list(name, default=None):
    if default is None:
        default = []
    raw_value = os.environ.get(name)
    if not raw_value:
        return default
    return [item.strip() for item in raw_value.split(',') if item.strip()]

DEBUG = _config_flag('DEBUG', default=True)
TESTING = 'test' in sys.argv

SECRET_KEY = os.environ.get('SECRET_KEY', '')
if not SECRET_KEY:
    if DEBUG:
        SECRET_KEY = 'hanilies-cakeshoppe-local-dev-secret-key-2024-only'
    else:
        raise ImproperlyConfigured('SECRET_KEY must be set when DEBUG is False.')

ALLOWED_HOSTS = _config_list(
    'ALLOWED_HOSTS',
    ['hanilies-cakeshoppe-non1.onrender.com', 'localhost', '127.0.0.1', '.onrender.com'],
)

CSRF_TRUSTED_ORIGINS = _config_list(
    'CSRF_TRUSTED_ORIGINS',
    ['https://hanilies-cakeshoppe-non1.onrender.com', 'https://*.onrender.com'],
)

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'hanilies',  # Your app
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],  # Your templates folder
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': Path(os.environ.get('SQLITE_PATH', BASE_DIR / 'db.sqlite3')),
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]

LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True

# Static files (CSS, JavaScript, Images)
STATIC_URL = '/static/'
STATICFILES_DIRS = [BASE_DIR / 'static']
STATIC_ROOT = BASE_DIR / 'staticfiles'

STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"

# Media files
MEDIA_URL = '/media/'
MEDIA_ROOT = Path(os.environ.get('MEDIA_ROOT', BASE_DIR / 'media'))

# Authentication URLs
LOGIN_URL = '/login/'

LOGIN_REDIRECT_URL = '/'
LOGOUT_REDIRECT_URL = '/'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
SECURE_SSL_REDIRECT = _config_flag(
    'SECURE_SSL_REDIRECT',
    default=not DEBUG and not TESTING,
)
SESSION_COOKIE_SECURE = _config_flag(
    'SESSION_COOKIE_SECURE',
    default=not DEBUG and not TESTING,
)
CSRF_COOKIE_SECURE = _config_flag(
    'CSRF_COOKIE_SECURE',
    default=not DEBUG and not TESTING,
)
SECURE_HSTS_SECONDS = int(
    os.environ.get('SECURE_HSTS_SECONDS', '3600' if not DEBUG and not TESTING else '0')
)
SECURE_HSTS_INCLUDE_SUBDOMAINS = _config_flag(
    'SECURE_HSTS_INCLUDE_SUBDOMAINS',
    default=False,
)
SECURE_HSTS_PRELOAD = _config_flag('SECURE_HSTS_PRELOAD', default=False)

EMAIL_BACKEND = os.environ.get(
    'EMAIL_BACKEND',
    'django.core.mail.backends.console.EmailBackend' if DEBUG else 'django.core.mail.backends.smtp.EmailBackend',
)
EMAIL_HOST = os.environ.get('EMAIL_HOST', 'smtp.gmail.com')
EMAIL_PORT = int(os.environ.get('EMAIL_PORT', '587'))
EMAIL_HOST_USER = os.environ.get('EMAIL_HOST_USER', '')
EMAIL_HOST_PASSWORD = os.environ.get('EMAIL_HOST_PASSWORD', '')
EMAIL_USE_TLS = _config_flag('EMAIL_USE_TLS', default=True)
EMAIL_USE_SSL = _config_flag('EMAIL_USE_SSL', default=False)
DEFAULT_FROM_EMAIL = os.environ.get(
    'DEFAULT_FROM_EMAIL',
    'noreply@hanilies.local',
)

DEMO_BOT_REMOTE_ENABLED = _config_flag('DEMO_BOT_REMOTE_ENABLED', default=False)

HANILIES_GCASH_ACCOUNT_NAME = os.environ.get(
    'HANILIES_GCASH_ACCOUNT_NAME',
    'Hanilies Cakeshoppe',
)
HANILIES_GCASH_ACCOUNT_NUMBER = os.environ.get(
    'HANILIES_GCASH_ACCOUNT_NUMBER',
    '09171234567',
)
HANILIES_GCASH_PAYMENT_NOTE = os.environ.get(
    'HANILIES_GCASH_PAYMENT_NOTE',
    'Scan this QR to copy the payment instructions on another device, or open GCash and send payment manually using the account below.',
)

# Production security settings for Render
if not DEBUG:
    SECURE_SSL_REDIRECT = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
