from django.contrib import admin

from .models import Document, EspaceChantier, Evenement, Intervenant, ProjetArchive, Version


@admin.register(EspaceChantier)
class EspaceChantierAdmin(admin.ModelAdmin):
    list_display = ("projet", "statut", "ouvert_le", "notifications")


@admin.register(Intervenant)
class IntervenantAdmin(admin.ModelAdmin):
    list_display = ("nom", "espace", "profil", "actif", "dernier_acces", "code_fin")
    list_filter = ("profil", "actif")
    exclude = ("code_empreinte",)


class VersionInline(admin.TabularInline):
    model = Version
    extra = 0
    fields = ("indice", "nom_original", "deposee_par_nom", "deposee_le", "visa", "vise_le")
    readonly_fields = fields


@admin.register(Document)
class DocumentAdmin(admin.ModelAdmin):
    list_display = ("reference", "titre", "espace", "zone", "lot", "categorie", "annule")
    list_filter = ("zone", "categorie", "annule")
    search_fields = ("reference", "titre")
    inlines = [VersionInline]


@admin.register(Evenement)
class EvenementAdmin(admin.ModelAdmin):
    list_display = ("date", "espace", "type", "acteur", "description")
    list_filter = ("type",)


@admin.register(ProjetArchive)
class ProjetArchiveAdmin(admin.ModelAdmin):
    list_display = ("nom_projet", "statut", "cree_le", "taille", "projet_supprime_le")
