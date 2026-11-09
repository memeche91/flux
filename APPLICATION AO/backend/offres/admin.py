from django.contrib import admin

from .models import AnalyseLot, Offre


@admin.register(Offre)
class OffreAdmin(admin.ModelAdmin):
    list_display = ("lot", "entreprise", "variante", "montant_base", "statut_lecture", "ecartee")
    list_filter = ("statut_lecture", "ecartee")


admin.site.register(AnalyseLot)
