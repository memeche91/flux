from django.apps import AppConfig


class GedConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "ged"
    verbose_name = "GED de chantier"

    def ready(self):
        from . import signaux  # noqa: F401
