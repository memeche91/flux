from django.contrib import admin

from .models import Acces, Document, EspaceChantier, Evenement, Intervenant, ProjetArchive, Version


@admin.register(EspaceChantier)
class EspaceChantierAdmin(admin.ModelAdmin):
    list_display = ("projet", "statut", "ouvert_le", "notifications", "lecture_inter_lots")


class AccesInline(admin.TabularInline):
    model = Acces
    extra = 0
    fields = ("nom", "email", "frequence", "actif", "code_fin", "dernier_acces")
    readonly_fields = ("code_fin", "dernier_acces")


@admin.register(Intervenant)
class IntervenantAdmin(admin.ModelAdmin):
    list_display = ("nom", "espace", "profil", "actif")
    list_filter = ("profil", "actif")
    inlines = [AccesInline]


class VersionInline(admin.TabularInline):
    model = Version
    extra = 0
    fields = ("indice", "nom_original", "deposee_par_nom", "deposee_le", "diffusion", "visa", "echeance_visa", "vise_le")
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
    list_display = ("nom_projet", "statut", "cree_le", "taille", "fichiers_purges_le")
