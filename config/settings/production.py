from .base import *

DEBUG = False

ALLOWED_HOSTS = [
    "your-domain.com",
    "YOUR_EC2_IP"
]


# DATABASE AWS (DOCKER)
DATABASES['default']['HOST'] = 'db'


# CHANNELS AWS
CHANNEL_LAYERS = {
    'default': {
        'BACKEND': 'channels_redis.core.RedisChannelLayer',
        'CONFIG': {
            "hosts": [('redis', 6379)],
        },
    },
}


# CELERY AWS
CELERY_BROKER_URL = 'redis://redis:6379/0'
CELERY_RESULT_BACKEND = 'redis://redis:6379/0'


# CORS AWS
CORS_ALLOWED_ORIGINS = [
    "https://yourdomain.com"
]