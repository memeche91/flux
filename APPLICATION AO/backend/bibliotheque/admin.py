from django.contrib import admin

from .models import DocumentReference


@admin.register(DocumentReference)
class DocumentReferenceAdmin(admin.ModelAdmin):
    list_display = ("nom_original", "type_document", "lot", "operation", "annee", "statut_analyse", "ajoute_le")
    list_filter = ("type_document", "lot", "statut_analyse", "type_marche")
    search_fields = ("nom_original", "operation")
    readonly_fields = ("empreinte_sha256", "taille", "ajoute_par", "ajoute_le", "message_analyse", "texte_extrait")
