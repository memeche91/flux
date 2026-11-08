"""Tâches de fond (analyse des documents, exports, IA, e-mails)."""
import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

app = Celery("application_ao")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()
