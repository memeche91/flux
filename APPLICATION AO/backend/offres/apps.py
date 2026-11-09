from django.apps import AppConfig


class OffresConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "offres"
    verbose_name = "Analyse des offres"

    def ready(self):
        from . import signaux  # noqa: F401
