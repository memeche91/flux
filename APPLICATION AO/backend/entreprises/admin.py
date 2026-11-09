from django.contrib import admin

from .models import Contact, Entreprise


class ContactEnLigne(admin.TabularInline):
    model = Contact
    extra = 0


@admin.register(Entreprise)
class EntrepriseAdmin(admin.ModelAdmin):
    list_display = ("raison_sociale", "ville", "email", "actif")
    list_filter = ("actif", "lots")
    search_fields = ("raison_sociale", "siret", "ville")
    filter_horizontal = ("lots",)
    inlines = [ContactEnLigne]
