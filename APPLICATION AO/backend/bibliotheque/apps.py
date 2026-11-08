from django.apps import AppConfig


class BibliothequeConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "bibliotheque"
    verbose_name = "Bibliothèque documentaire"

    def ready(self):
        from . import signaux  # noqa: F401
