# config/celery.py
import os
from celery import Celery

# Set Django settings module (this matches your structure)
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

app = Celery('luktaa')  # app name can be anything, 'luktaa' is fine

# Load configuration from Django settings with CELERY_ prefix
app.config_from_object('django.conf:settings', namespace='CELERY')

# Auto-discover tasks in all installed apps (including admin_api.tasks)
app.autodiscover_tasks()

 