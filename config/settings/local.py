from .base import *

DEBUG = True

ALLOWED_HOSTS = ['*']


# =========================
# DATABASE (DOCKER LOCAL)
# =========================
DATABASES['default']['HOST'] = 'db'


# =========================
# REDIS / CHANNELS
# =========================
CHANNEL_LAYERS = {
    'default': {
        'BACKEND': 'channels_redis.core.RedisChannelLayer',
        'CONFIG': {
            "hosts": [('redis', 6379)],
        },
    },
}


# =========================
# CELERY
# =========================
CELERY_BROKER_URL = 'redis://redis:6379/0'
CELERY_RESULT_BACKEND = 'redis://redis:6379/0'


# =========================
# CORS
# =========================
CORS_ALLOWED_ORIGINS = [
    "http://localhost:3000",
]