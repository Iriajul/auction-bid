from pathlib import Path
import environ
from datetime import timedelta
import cloudinary
from corsheaders.defaults import default_headers

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# environ setup
env = environ.Env(DEBUG=(bool, False))
environ.Env.read_env(BASE_DIR / '.env')

# SECURITY
SECRET_KEY = env('SECRET_KEY')
DEBUG = env.bool('DEBUG', default=True)

ALLOWED_HOSTS = ['*']  # change in production!!

# --------------------------------------------------
# CORS CONFIGURATION (FOR FRONTEND)
# --------------------------------------------------
CORS_ALLOWED_ORIGINS = [
    "http://localhost:3000",
    'https://ffm803lb-8000.inc1.devtunnels.ms',
    'http://10.10.13.33:3000'
]

CSRF_TRUSTED_ORIGINS = [
    "https://ffm803lb-8000.inc1.devtunnels.ms",
]


CORS_ALLOW_CREDENTIALS = True


CORS_ALLOW_HEADERS = list(default_headers) + [
    'authorization',
]

# Application definition
INSTALLED_APPS = [
    'corsheaders',
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',

    'rest_framework',
    'rest_framework_simplejwt',

    # Cloudinary packages - BOTH required
    'cloudinary',
    'channels',
    'cloudinary_storage',
    'django_celery_beat',
    'fcm_django',

    # your apps
    'apps.users',
    'apps.admin_api',
    'apps.packages',
    'apps.auction',
    'apps.winner_claim',
    'apps.products',
    'apps.cart',
    'apps.wishlist',
    # 'apps.auctions',
    # 'apps.wallet',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'corsheaders.middleware.CorsMiddleware',
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
        'DIRS': [],
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

# DATABASE - PostgreSQL with custom schema 'mohmt'
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': env('DB_NAME'),
        'USER': env('DB_USER'),
        'PASSWORD': env('DB_PASSWORD'),
        'HOST': env('DB_HOST', default='localhost'),
        'PORT': env('DB_PORT', default='5432'),
        # 'OPTIONS': {
        #     'options': '-c search_path=mohmt'
        # },
    }
}

# ASGI application
ASGI_APPLICATION = 'config.asgi.application'

# Channel layers (use Redis for production)
CHANNEL_LAYERS = {
    'default': {
        'BACKEND': 'channels_redis.core.RedisChannelLayer',
        'CONFIG': {
            "hosts": [('redis', 6379)],
        },
    },
}

# Password validation
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

# Internationalization
LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'Asia/Dhaka'
USE_I18N = True
USE_TZ = True

# Static files (CSS, JavaScript, Images)
STATIC_URL = 'static/'

STATIC_ROOT = BASE_DIR / 'staticfiles'

# Where Django will look for static files (for development)
STATICFILES_DIRS = [
    BASE_DIR / 'static',
]

# Default primary key field type
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# AUTHENTICATION & CUSTOM USER
AUTH_USER_MODEL = 'users.User'

# REST FRAMEWORK + JWT
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': (
        'rest_framework_simplejwt.authentication.JWTAuthentication',
    ),
    'DEFAULT_PERMISSION_CLASSES': (
        'rest_framework.permissions.AllowAny',   # change later to IsAuthenticated
    ),
}

SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(minutes=env.int('ACCESS_TOKEN_LIFETIME_MINUTES', 100080)),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=env.int('REFRESH_TOKEN_LIFETIME_DAYS', 7)),
    'ROTATE_REFRESH_TOKENS': True,
    'BLACKLIST_AFTER_ROTATION': True,
}

# For development convenience
if DEBUG:
    import warnings
    warnings.filterwarnings("ignore", message=".*has been deprecated.*")



# Celery Configuration
CELERY_BROKER_URL = 'redis://redis:6379/0'
CELERY_RESULT_BACKEND = 'redis://redis:6379/0'
CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_SERIALIZER = 'json'
CELERY_RESULT_SERIALIZER = 'json'
CELERY_TIMEZONE = 'Asia/Dhaka'


# Use database-backed scheduler (so tasks persist even after restart)
CELERY_BEAT_SCHEDULER = 'django_celery_beat.schedulers:DatabaseScheduler'



# CLOUDINARY CONFIG
CLOUDINARY = {
    "cloud_name": env("CLOUDINARY_CLOUD_NAME"),
    "api_key": env("CLOUDINARY_API_KEY"),
    "api_secret": env("CLOUDINARY_API_SECRET"),
}

cloudinary.config(
    cloud_name=CLOUDINARY["cloud_name"],
    api_key=CLOUDINARY["api_key"],
    api_secret=CLOUDINARY["api_secret"],
)

DEFAULT_FILE_STORAGE = 'cloudinary_storage.storage.MediaCloudinaryStorage'

# EMAIL CONFIGURATION
EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
EMAIL_HOST = env("EMAIL_HOST")
EMAIL_PORT = env.int("EMAIL_PORT", default=587)
EMAIL_USE_TLS = env.bool("EMAIL_USE_TLS", default=True)
EMAIL_HOST_USER = env("EMAIL_HOST_USER")
EMAIL_HOST_PASSWORD = env("EMAIL_HOST_PASSWORD")
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL")


# --------------------------------------------------
# STRIPE CONFIGURATION
# --------------------------------------------------
STRIPE_SECRET_KEY = env("STRIPE_SECRET_KEY")
STRIPE_PUBLISHABLE_KEY = env("STRIPE_PUBLISHABLE_KEY")
STRIPE_WEBHOOK_SECRET = env("STRIPE_WEBHOOK_SECRET")



# --------------------------------------------------
# LOGGING
# --------------------------------------------------
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "level": "INFO",
        },
    },
    "root": {
        "handlers": ["console"],
        "level": "INFO",
    },
}


CELERY_BEAT_SCHEDULE = {
    # Publish scheduled auctions every 1 minute
    'publish-scheduled-auctions': {
        'task': 'apps.admin_api.tasks.publish_scheduled_auctions',
        'schedule': 60.0,  # every 60 seconds
    },
    # End expired auctions every 2 seconds for near real-time ending
    'end-expired-auctions': {
        'task': 'apps.admin_api.tasks.end_expired_auctions',
        'schedule': 2.0,  # every 2 seconds
    },
}

# ────────────────────────────────────────────────
# Firebase Admin SDK (for push notifications)
# ────────────────────────────────────────────────
try:
    import firebase_init
    firebase_init  # just importing runs the initialization
except Exception as e:
    print("WARNING: Could not initialize Firebase Admin SDK")
    print(e)