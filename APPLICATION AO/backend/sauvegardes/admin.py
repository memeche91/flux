from django.contrib import admin

from .models import Sauvegarde


@admin.register(Sauvegarde)
class SauvegardeAdmin(admin.ModelAdmin):
    """Historique en lecture seule : les sauvegardes se lancent depuis l'application ou la planification."""

    list_display = ("debut", "fin", "statut", "verifiee", "taille", "fichiers_copies", "declenchee_par")
    list_filter = ("statut", "verifiee")
    readonly_fields = ("debut", "fin", "statut", "fichier", "taille", "verifiee", "fichiers_copies", "message", "declenchee_par")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
